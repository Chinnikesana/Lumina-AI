# """
# Streaming endpoints for real-time document processing updates
# """

# import asyncio
# import json
# import uuid
# from typing import AsyncGenerator
# from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
# from fastapi.responses import StreamingResponse
# from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# from ..core.security import get_current_user_token
# from ..core.logger import get_logger
# from ..core.supabase_client import supabase_client
# from ..services.document_processing import document_processing_service
# from ..models.models import DocumentStatus

# router = APIRouter(prefix="/streaming", tags=["streaming"])
# logger = get_logger(__name__)

# async def process_document_stream(
#     document_id: str,
#     file_path: str,
#     narration_type: str,
#     user_input: str = None
# ) -> AsyncGenerator[str, None]:
#     """
#     Stream document processing updates as Server-Sent Events
#     """
#     try:
#         # Start document processing
#         async for update in document_processing_service.process_document(
#             document_id=document_id,
#             document_path=file_path,
#             narration_type=narration_type,
#             user_input=user_input
#         ):
#             # Format as SSE
#             sse_data = f"data: {json.dumps(update)}\n\n"
#             yield sse_data
            
#             # Add small delay to prevent overwhelming the client
#             await asyncio.sleep(0.1)
            
#     except Exception as e:
#         logger.error(f"Error in document processing stream: {str(e)}")
#         error_data = {
#             "type": "error",
#             "message": f"Processing failed: {str(e)}"
#         }
#         yield f"data: {json.dumps(error_data)}\n\n"

# @router.post("/process-document")
# async def start_document_processing(
#     file: UploadFile = File(...),
#     type: str = Form(...),
#     extra_input: str = Form(None),
#     token_data: dict = Depends(get_current_user_token)
# ):
#     """
#     Start document processing and return SSE stream
#     """
#     try:
#         user_id = token_data.get("user_id")
        
#         # Validate file type
#         if not file.filename.lower().endswith(('.pdf', '.doc', '.docx')):
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Invalid file type. Only PDF, DOC, and DOCX files are allowed"
#             )
        
#         # Validate narration type
#         valid_types = ['simple', 'medium', 'detail']
#         if type not in valid_types:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail=f"Invalid narration type. Must be one of: {valid_types}"
#             )
        
#         # Generate unique document ID
#         document_id = str(uuid.uuid4())
        
#         # Save file temporarily
#         import tempfile
#         import os
        
#         # Create temp directory if it doesn't exist
#         temp_dir = "temp_documents"
#         os.makedirs(temp_dir, exist_ok=True)
        
#         file_path = os.path.join(temp_dir, f"{document_id}_{file.filename}")
        
#         # Save uploaded file
#         with open(file_path, "wb") as buffer:
#             content = await file.read()
#             buffer.write(content)
        
#         # Create document record in database
#         document_data = {
#             "id": document_id,
#             "user_id": str(user_id),
#             "resource_url": file_path,  # Temporary path
#             "extra_input": extra_input,
#             "type": type,
#             "status": DocumentStatus.PROCESSING.value
#         }
        
#         response = supabase_client.table('documents').insert(document_data).execute()
        
#         if not response.data:
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail="Failed to create document record"
#             )
        
#         logger.info(f"Starting document processing for {document_id}")
        
#         # Return SSE stream
#         return StreamingResponse(
#             process_document_stream(
#                 document_id=document_id,
#                 file_path=file_path,
#                 narration_type=type,
#                 user_input=extra_input
#             ),
#             media_type="text/event-stream",
#             headers={
#                 "Cache-Control": "no-cache",
#                 "Connection": "keep-alive",
#                 "Access-Control-Allow-Origin": "*",
#                 "Access-Control-Allow-Headers": "Cache-Control"
#             }
#         )
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error starting document processing: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to start document processing"
#         )

# @router.get("/document-status/{document_id}")
# async def get_document_processing_status(
#     document_id: str,
#     token_data: dict = Depends(get_current_user_token)
# ):
#     """
#     Get the current processing status of a document
#     """
#     try:
#         user_id = token_data.get("user_id")
        
#         # Get document from database
#         response = supabase_client.table('documents').select('*').eq('id', document_id).eq('user_id', str(user_id)).execute()
        
#         if not response.data:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Document not found"
#             )
        
#         document = response.data[0]
        
#         return {
#             "document_id": document_id,
#             "status": document["status"],
#             "created_at": document["created_at"],
#             "last_updated": document["last_updated"]
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting document status: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to get document status"
#         )
