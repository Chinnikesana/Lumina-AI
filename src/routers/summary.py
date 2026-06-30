import json
import traceback
from fastapi import APIRouter, HTTPException, status, Query

from ..core.supabase_client import supabase_client
from ..core.logger import get_logger
from ..core.llm_client import call_llm, parse_json_response

router = APIRouter()
logger = get_logger(__name__)

@router.get("/{document_id}/summary")
async def get_summary(document_id: str, user_id: str = Query(...)):
    """
    Retrieves a pre-generated summary for a document if it exists.
    This provides a fast-loading experience for the user on subsequent visits.
    """
    
    # Verify the document exists and belongs to the user before returning data
    doc_resp = supabase_client.table('documents').select('summary').eq('document_id', document_id).eq('user_id', user_id).single().execute()

    if not doc_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found or access is denied.")

    return {"summary": doc_resp.data.get("summary")}


@router.post("/{document_id}/summary")
async def generate_and_store_summary(document_id: str, user_id: str = Query(...)):
    """
    Generates a new, detailed summary for a document using its stored markdown content.
    This is called by the frontend when the user wants to generate a summary for the first time.
    """

    # Verify document ownership and retrieve its pre-parsed markdown content
    doc_resp = supabase_client.table('documents').select('doc_content').eq('document_id', document_id).eq('user_id', user_id).single().execute()
    summary_resp = supabase_client.table('documents').select('summary').eq('document_id', document_id).eq('user_id', user_id).single().execute()
        
    doc_content = doc_resp.data.get("doc_content") if doc_resp.data else None
    if not doc_content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document content has not been processed and is unavailable for summarization.")

    logger.info(f"Generating summary for document_id {document_id} using LLM client...")
    
    # This detailed prompt guides the LLM to act as a tutor and structure the summary effectively.
    prompt = (
        "You are an expert educator with a talent for making complex topics easy to understand. Your task is to read the following document content and create a detailed, yet simple, summary. "
        "The goal is to give someone a complete and clear understanding of the document's key information, as if you were explaining it to them after they've listened to a full narration.\n\n"
        "**Document Content:**\n---\n"
        f"{doc_content}\n"
        "---\n\n"
        "**Your Task:**\n"
        "Generate the summary in two parts. First, a narrative paragraph that tells the overall 'story' of the document. Second, a list of detailed bullet points that capture the most critical facts, findings, and conclusions.\n"
        "Use simple, accessible language throughout.\n\n"
        "**Required JSON Output Format:**\n"
        "Respond ONLY with a valid JSON object. Do not include any other text or markdown formatting.\n"
        "{\n"
        "  \"narrative_summary\": \"A well-written paragraph (or two) that explains the main purpose and flow of the document in simple terms.\",\n"
        "  \"key_points\": [\n"
        "    \"The first detailed key takeaway. This should be a complete sentence.\",\n"
        "    \"The second important fact or conclusion from the document.\",\n"
        "    \"...and so on, for all major points.\"\n"
        "  ]\n"
        "}"
    )

    try:
        response_text = await call_llm(
            prompt=prompt,
            temperature=0.5,
            json_mode=True
        )
        
        summary_data = parse_json_response(response_text)
        
        # Save the newly generated summary back to the database for future fast retrieval
        update_resp = supabase_client.table('documents').update({
            'summary': summary_data
        }).eq('document_id', document_id).execute()

        if not update_resp.data:
            # This would indicate a potential DB issue, but we can still return the summary
            logger.warning(f"Summary was generated but failed to save for document_id {document_id}.")
        
        logger.info(f"Successfully generated and saved summary for document_id {document_id}.")
        return {"summary": summary_data}

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON from LLM response for document_id {document_id}")
        raise HTTPException(status_code=500, detail="Failed to parse summary from AI response. Please try again.")
    except Exception as e:
        logger.error(f"Failed to generate summary for document_id {document_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred while generating the summary.")
