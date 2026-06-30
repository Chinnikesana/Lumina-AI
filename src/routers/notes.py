from fastapi import APIRouter, HTTPException, status, Query, Body
from pydantic import BaseModel
import traceback

from ..core.supabase_client import supabase_client
from ..core.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

# Pydantic model for the request body to ensure data is structured correctly
class NotePayload(BaseModel):
    note_content: str

@router.get("/{doc_id}/notes")
async def get_note(doc_id: str, user_id: str = Query(...)):
    """
    Retrieves the saved note for a specific document, if one exists.
    """
    logger.info(f"GET /notes request for doc_id: {doc_id}")

    # Security: First, verify the user has access to the parent document
    doc_resp = supabase_client.table('documents').select('document_id').eq('document_id', doc_id).eq('user_id', user_id).single().execute()
    if not doc_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found or access denied.")

    # Fetch the note associated with the document
    note_resp = supabase_client.table('notes').select('note_id, note_content, last_updated').eq('document_id', doc_id).single().execute()
    
    if note_resp.data:
        return note_resp.data
    else:
        # It's not an error if no note exists, just return an empty response
        return {"note_id": None, "note_content": "", "last_updated": None}

@router.post("/{doc_id}/notes")
async def save_note(doc_id: str, user_id: str = Query(...), payload: NotePayload = Body(...)):
    """
    Creates a new note or updates an existing one for a specific document (Upsert).
    """
    logger.info(f"POST /notes request for doc_id: {doc_id}")

    # Security: Verify the user has access to the parent document
    doc_resp = supabase_client.table('documents').select('document_id').eq('document_id', doc_id).eq('user_id', user_id).single().execute()
    if not doc_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found or access denied.")

    try:
        # Use the 'upsert' method to handle both INSERT and UPDATE in one operation.
        # It will look for an existing row with the same 'document_id'.
        # If it finds one, it updates it. If not, it inserts a new row.
        response = supabase_client.table('notes').upsert({
            'document_id': doc_id,
            'user_id': user_id,
            'note_content': payload.note_content
        }, on_conflict='document_id').execute()

        if not response.data:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save note to database.")

        logger.info(f"Successfully saved note for doc_id: {doc_id}")
        return {"status": "success", "message": "Note saved successfully."}

    except Exception as e:
        logger.error(f"Failed to save note for doc_id {doc_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred while saving the note.")