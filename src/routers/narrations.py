"""
Narration management endpoints
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from ..core.security import get_current_user_token
from ..core.supabase_client import supabase_client
from ..core.logger import get_logger
from ..models.models import (
    NarrationCreate, NarrationResponse, NarrationUpdate, NarrationStatus,
    NarrationBboxData
)

router = APIRouter()
logger = get_logger(__name__)

@router.post("/", response_model=NarrationResponse, status_code=status.HTTP_201_CREATED)
async def create_narration(
    narration_data: NarrationCreate,
    token_data: dict = Depends(get_current_user_token)
):
    """
    Create a new narration for a document
    
    - **narration_data**: Narration creation data
    """
    try:
        user_id = token_data.get("user_id")
        
        # Validate document exists and belongs to user
        doc_response = supabase_client.table('documents').select('*').eq('id', str(narration_data.document_id)).eq('user_id', str(user_id)).execute()
        
        if not doc_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Create narration record
        narration_record = {
            "document_id": str(narration_data.document_id),
            "context": narration_data.context,
            "narration_bbox": narration_data.narration_bbox.dict() if narration_data.narration_bbox else None,
            "status": NarrationStatus.PENDING.value
        }
        
        response = supabase_client.table('narrations').insert(narration_record).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create narration record"
            )
        
        narration = response.data[0]
        logger.info(f"Narration created successfully: {narration['id']}")
        
        return NarrationResponse(**narration)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating narration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create narration"
        )

@router.get("/{narration_id}", response_model=NarrationResponse)
async def get_narration(
    narration_id: str,
    token_data: dict = Depends(get_current_user_token)
):
    """
    Get narration details by ID
    
    - **narration_id**: UUID of the narration
    """
    try:
        user_id = token_data.get("user_id")
        
        # Validate UUID format
        try:
            uuid.UUID(narration_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid narration ID format"
            )
        
        # Get narration with document info to verify ownership
        response = supabase_client.table('narrations').select(
            '*, documents!inner(user_id)'
        ).eq('id', narration_id).eq('documents.user_id', str(user_id)).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Narration not found"
            )
        
        narration = response.data[0]
        logger.info(f"Narration retrieved: {narration_id}")
        
        return NarrationResponse(**narration)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving narration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve narration"
        )

@router.get("/document/{document_id}", response_model=List[NarrationResponse])
async def get_document_narrations(
    document_id: str,
    token_data: dict = Depends(get_current_user_token)
):
    """
    Get all narrations for a specific document
    
    - **document_id**: UUID of the document
    """
    try:
        user_id = token_data.get("user_id")
        
        # Validate UUID format
        try:
            uuid.UUID(document_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid document ID format"
            )
        
        # Verify document belongs to user
        doc_response = supabase_client.table('documents').select('*').eq('id', document_id).eq('user_id', str(user_id)).execute()
        
        if not doc_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Get narrations for document
        response = supabase_client.table('narrations').select('*').eq('document_id', document_id).order('created_at', desc=True).execute()
        
        narrations = response.data or []
        logger.info(f"Retrieved {len(narrations)} narrations for document {document_id}")
        
        return [NarrationResponse(**narration) for narration in narrations]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving document narrations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve narrations"
        )

@router.put("/{narration_id}", response_model=NarrationResponse)
async def update_narration(
    narration_id: str,
    narration_update: NarrationUpdate,
    token_data: dict = Depends(get_current_user_token)
):
    """
    Update narration details
    
    - **narration_id**: UUID of the narration
    - **narration_update**: Narration update data
    """
    try:
        user_id = token_data.get("user_id")
        
        # Validate UUID format
        try:
            uuid.UUID(narration_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid narration ID format"
            )
        
        # Check if narration exists and belongs to user
        response = supabase_client.table('narrations').select(
            '*, documents!inner(user_id)'
        ).eq('id', narration_id).eq('documents.user_id', str(user_id)).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Narration not found"
            )
        
        # Prepare update data
        update_data = {}
        if narration_update.context is not None:
            update_data['context'] = narration_update.context
        if narration_update.narration_bbox is not None:
            update_data['narration_bbox'] = narration_update.narration_bbox.dict()
        if narration_update.status is not None:
            update_data['status'] = narration_update.status.value
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )
        
        # Update narration
        response = supabase_client.table('narrations').update(update_data).eq('id', narration_id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update narration"
            )
        
        narration = response.data[0]
        logger.info(f"Narration updated: {narration_id}")
        
        return NarrationResponse(**narration)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating narration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update narration"
        )

@router.delete("/{narration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_narration(
    narration_id: str,
    token_data: dict = Depends(get_current_user_token)
):
    """
    Delete a narration
    
    - **narration_id**: UUID of the narration
    """
    try:
        user_id = token_data.get("user_id")
        
        # Validate UUID format
        try:
            uuid.UUID(narration_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid narration ID format"
            )
        
        # Check if narration exists and belongs to user
        response = supabase_client.table('narrations').select(
            '*, documents!inner(user_id)'
        ).eq('id', narration_id).eq('documents.user_id', str(user_id)).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Narration not found"
            )
        
        # Delete narration
        response = supabase_client.table('narrations').delete().eq('id', narration_id).execute()
        
        logger.info(f"Narration deleted: {narration_id}")
        
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting narration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete narration"
        )
