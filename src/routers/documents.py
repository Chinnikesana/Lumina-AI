

import os
import uuid
import json
import tempfile
import traceback
from typing import List, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, Query, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.supabase_client import supabase_client
from ..core.logger import get_logger
from ..models.models import (
    DocumentCreate, DocumentResponse, DocumentUpdate, DocumentStatus,
    DocumentType
)
from ..services.document_processing_service import document_processing_service

router = APIRouter()
logger = get_logger(__name__)

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    type: str = Form(...),
    extra_input: str = Form(None),
    user_id: str = Form(...),
):
    """
    Handles document upload, triggers initial processing, and queues
    chat indexing as a non-blocking background task.
    """
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id")
    
    local_path = None  # Initialize to ensure it's available in the finally block
    try:
        doc_type = DocumentType(type.lower())
        
        if not file.filename.lower().endswith(('.pdf',)): # Currently optimized for PDF
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file type. Only PDF files are supported.")

        document_id = str(uuid.uuid4())
        storage_rel_path = f"user_{user_id}/{document_id}/original_{file.filename}"
        file_bytes = await file.read()
        
        # 1. Upload to storage
        inferred_ct = 'application/pdf'
        supabase_client.storage.from_("docs_store").upload(
            storage_rel_path, file_bytes, file_options={"content-type": inferred_ct, "x-upsert": "true"}
        )

        # 2. Create the document record in the database
        document_data = {
            "document_id": document_id, "user_id": str(user_id),
            "resource_url": f"docs_store/{storage_rel_path}", "extra_input": extra_input,
            "type": doc_type.value, "status": DocumentStatus.PROCESSING.value,
            "title": file.filename, "description": (extra_input or "").strip(),
        }
        supabase_client.table('documents').insert(document_data).execute()

        # 3. Create a temporary local file for processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            tmp.write(file_bytes)
            local_path = tmp.name
        
        # 4. Run the initial, synchronous part of the processing (parsing, overview, etc.)
        logger.info(f"Starting initial processing for document_id: {document_id}")
        initial_narration_data = await document_processing_service.initial_processing(
            document_id=document_id, local_path=local_path, user_input=extra_input
        )

        # 5. Queue the long-running background task for chat indexing
        background_tasks.add_task(document_processing_service.index_document_for_chat, document_id)
        logger.info(f"Queued background chat indexing for doc_id: {document_id}")
        
        # 6. Get a signed URL for the frontend to use immediately
        signed_url = None
        try:
            signed = supabase_client.storage.from_("docs_store").create_signed_url(storage_rel_path, 60 * 105) # ~1.75 hours
            signed_url = signed.get('signedURL') or signed.get('signed_url')
        except Exception as e:
            logger.warning(f"Failed to create signed URL: {e}")

        # 7. Return the immediate response to the user
        return {
            "document_id": document_id,
            "resource_url": signed_url,
            **initial_narration_data
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed critically: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to upload document: {e}")
    finally:
        # 8. Ensure the temporary file is always cleaned up
        if local_path and os.path.exists(local_path):
            os.unlink(local_path)
            logger.info(f"Cleaned up temp file: {local_path}")




@router.get("/stream/{document_id}")
async def stream_document_narrations(
    document_id: str,
    request: Request,
    user_id: str = Query(...)
):
    """SSE: Stream narration chunks for a given document."""
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id")

    doc_resp = supabase_client.table('documents').select('document_id').eq('document_id', document_id).eq('user_id', user_id).execute()
    if not doc_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found or access denied")

    async def event_generator():
        try:
            async for evt in document_processing_service.stream_narration_chunks(document_id, user_id):
                if await request.is_disconnected():
                    logger.info("Client disconnected, stopping stream.")
                    break
                yield f"data: {json.dumps(evt)}\n\n"
        except Exception as e:
            logger.error(f"Streaming failed for document {document_id}: {e}")
            traceback.print_exc()
            err = {"type": "error", "message": f"An unexpected error occurred during streaming: {e}"}
            yield f"data: {json.dumps(err)}\n\n"
        print("Streaming completed for document", document_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

    

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    user_id: str = Query(...)
):
    """
    Get document details by ID
    
    - **document_id**: UUID of the document
    """
    try:
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id")
        
       
        
        # Get document from database
        response = supabase_client.table('documents').select('*').eq('document_id', document_id).eq('user_id', str(user_id)).eq('status', 'completed').execute()
        narration_response = supabase_client.table('narrations').select('*').eq('document_id', document_id).execute()

        narration = narration_response.data[0] if narration_response.data else None
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        document = response.data[0]
        

        # Create a signed URL for private storage paths
        resource_url = document.get('resource_url')
        signed_url = resource_url
        try:
            if resource_url and isinstance(resource_url, str) and resource_url.startswith('docs_store/'):
                rel_path = resource_url.split('docs_store/', 1)[1]
                # 5 minutes expiry
                signed = supabase_client.storage.from_("docs_store").create_signed_url(rel_path, 60 * 105)
                # Supabase client may return dict with 'signedURL' or 'signed_url'
                signed_url = signed.get('signedURL') or signed.get('signed_url') or signed_url
        except Exception as e:
            logger.warning(f"Failed to create signed URL for {resource_url}: {e}")

        # Map DB record to response model fields; provide safe fallbacks
        payload = {
            "id": document.get("document_id"),
            "user_id": document.get("user_id"),
            "resource_url": signed_url,
            "title": document.get("title"),
            "extra_input": document.get("extra_input"),
            "type": document.get("type") or "simple",
            "narration": (narration or {}).get("narration_bbox", ""),
            "created_at": document.get("created_at"),
            "last_updated": document.get("last_updated") or document.get("created_at"),
            "status": document.get("status") or "processing",
        }
        print("payload:", payload)

        return payload
        

    except Exception as e:
        logger.error(f"Error retrieving document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve document"
        )



@router.get("/")
async def get_user_documents(
    user_id: str = Query(...)
):
    """
    Get all documents for the current user
    """
    try:
        effective_user_id = str(user_id)
        print("before fetching docs")
        
        # Get all documents for user
        response = supabase_client.table('documents').select('*').eq('user_id', effective_user_id).eq('status', 'completed').order('created_at', desc=True).execute()
        print("trying to fetch all the docs of user ")
        documents = response.data or []
        logger.info(f"Retrieved {len(documents)} documents for user {effective_user_id}")
        # Map to required fields
        mapped = []
        for doc in documents:
            mapped.append({
                "document_id": doc.get("document_id"),
                "title": doc.get("title"),
                "last_updated": doc.get("last_updated"),
                "created_at": doc.get("created_at"),
                "status": doc.get("status"),
                "description": doc.get("description"),
            })
        return mapped
        
    except Exception as e:
        logger.error(f"Error retrieving user documents: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve documents"
        )























@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    document_update: DocumentUpdate,
    user_id: str = Query(...)
):
    """
    Update document details
    
    - **document_id**: UUID of the document
    - **document_update**: Document update data
    """
    try:
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id")
        
        # Check if document exists and belongs to user
        response = supabase_client.table('documents').select('*').eq('document_id', document_id).eq('user_id', str(user_id)).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Prepare update data
        update_data = {}
        if document_update.extra_input is not None:
            update_data['extra_input'] = document_update.extra_input
        if document_update.type is not None:
            update_data['type'] = document_update.type.value
        if document_update.status is not None:
            update_data['status'] = document_update.status.value
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )
        
        # Update document
        response = supabase_client.table('documents').update(update_data).eq('document_id', document_id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update document"
            )
        
        document = response.data[0]
        logger.info(f"Document updated: {document_id}")
        
        return DocumentResponse(**document)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update document"
        )

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    user_id: str = Query(...)
):
    """
    Delete a document
    
    - **document_id**: UUID of the document
    """
    try:
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id")
     
        # Check if document exists and belongs to user
        response = supabase_client.table('documents').select('*').eq('document_id', document_id).eq('user_id', str(user_id)).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Delete document (cascade will handle narrations)
        response = supabase_client.table('documents').delete().eq('document_id', document_id).execute()
        
        logger.info(f"Document deleted: {document_id}")
        
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document"
        )
