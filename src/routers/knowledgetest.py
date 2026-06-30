import json
import traceback
from fastapi import APIRouter, HTTPException, status, Query

from ..core.supabase_client import supabase_client
from ..core.logger import get_logger
from ..core.llm_client import call_llm, parse_json_response

router = APIRouter()
logger = get_logger(__name__)


@router.post("/{doc_id}/knowledgetest")
async def generate_knowledge_test(doc_id: str, user_id: str = Query(...)):
    """
    Generates a 15-question multiple-choice quiz based on the document's content.
    """

    # 1. Verify document ownership and retrieve its content
    doc_resp = supabase_client.table('documents').select('doc_content').eq('document_id', doc_id).eq('user_id', user_id).single().execute()

    if not doc_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found or access is denied.")
        
    doc_content = doc_resp.data.get("doc_content")
    if not doc_content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document content is not available for test generation.")

    # 2. Craft the Master Prompt for Q&A Generation
    prompt = (
        "You are an expert educator and skilled quiz designer. Your task is to create a comprehensive knowledge test based on the provided document content. The test must consist of exactly 15 multiple-choice questions.\n\n"
        "**Instructions:**\n"
        "1.  **Question Distribution:** Generate the questions with the following difficulty distribution:\n"
        "    -   5 **Easy** questions: These should test foundational concepts and key definitions.\n"
        "    -   5 **Medium** questions: These should require the user to apply concepts or interpret information.\n"
        "    -   5 **Hard** questions: These should challenge the user to synthesize information, evaluate scenarios, or solve complex problems based on the text.\n"
        "2.  **Full Coverage:** Ensure the questions cover the *entire breadth* of the document content, from beginning to end.\n"
        "3.  **Question Format:** Each question must be a multiple-choice question with exactly four options.\n"
        "4.  **Answer and Explanation:** For each question, you must identify the correct answer and provide a brief, clear explanation for why it is correct.\n\n"
        "**Document Content:**\n---\n"
        f"{doc_content}\n"
        "---\n\n"
        "**Required JSON Output Format:**\n"
        "Your response MUST be a single, valid JSON list of objects. Do not include any other text, markdown, or explanations outside of the JSON structure. Follow this format precisely:\n"
        "[\n"
        "  {\n"
        "    \"id\": \"1\",\n"
        "    \"question\": \"What is the primary concept discussed in the first section?\",\n"
        "    \"options\": [\n"
        "      \"Option A\",\n"
        "      \"Option B\",\n"
        "      \"The Correct Option\",\n"
        "      \"Option D\"\n"
        "    ],\n"
        "    \"correctAnswer\": 2, // The zero-based index of the correct option (0, 1, 2, or 3)\n"
        "    \"explanation\": \"A concise explanation of why the correct answer is right, based on the document's content.\"\n"
        "  },\n"
        "  { ... next question ... }\n"
        "]"
    )

    try:
        logger.info(f"Generating knowledge test for doc_id {doc_id} with LLM client...")
        
        response_text = await call_llm(
            prompt=prompt,
            temperature=0.4,
            json_mode=True
        )
        
        questions_data = parse_json_response(response_text)
        logger.info("Successfully generated knowledge test.")
        
        # Ensure it's returned as a dictionary with 'questions' key for frontend consistency if needed
        # Or return exactly what was previously returned. Previously it returned the JSON array directly.
        return questions_data

    except Exception as e:
        logger.error(f"Failed to generate knowledge test for doc_id {doc_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate knowledge test.")