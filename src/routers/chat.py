import json
import traceback
from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict
import uuid

from ..core.supabase_client import supabase_client
from ..core.logger import get_logger
from ..core.llm_client import call_llm
from ..core.embedding_client import get_single_embedding

router = APIRouter()
logger = get_logger(__name__)

@router.get("/{document_id}/chat")
async def get_chat_history(document_id: uuid.UUID, user_id: uuid.UUID = Query(...)):
    """Retrieves the chat history for a given document and user."""
    try:
        # Query for existing chat session
        session_resp = supabase_client.table('chat_sessions').select('chat_history, session_id')\
            .eq('document_id', str(document_id)).eq('user_id', str(user_id)).single().execute()
        
        if session_resp.data:
            session_data = session_resp.data
            return {
                "chat_session": session_data.get("chat_history", []),
                "session_id": session_data.get("session_id")
            }
        else:
            # No existing session found
            return {"chat_session": [], "session_id": None}
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch chat history")


@router.post("/{doc_id}/chat")
async def chat_with_document(doc_id: str, user_id: str = Query(...), request_body: Dict = Body(...)):
    query = request_body.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    # 1. Authenticate user access
    doc_resp = supabase_client.table('documents').select('document_id').eq('document_id', doc_id).eq('user_id', user_id).single().execute()
    if not doc_resp.data:
        raise HTTPException(status_code=404, detail="Document not found or access denied.")

    # 2. Fetch existing chat history
    session_resp = supabase_client.table('chat_sessions').select('session_id, chat_history').eq('document_id', doc_id).eq('user_id', user_id).execute()
    existing_history, session_id = (session_resp.data[0].get('chat_history', []), session_resp.data[0].get('session_id')) if session_resp.data else ([], None)

    # 3. Perform Vector Search (using HuggingFace Inference API instead of local sentence-transformers)
    try:
        query_embedding = await get_single_embedding(query)
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate embedding for vector search.")

    search_results = supabase_client.rpc('match_document_chunks', {
        'query_embedding': query_embedding, 'p_doc_id': doc_id, 'match_threshold': 0.10, 'match_count': 5
    }).execute().data

    logger.info(f"Vector search results count: {len(search_results) if search_results else 0}")

    answer = None
    if not search_results:
        answer = "I couldn't find any information in the document related to your question. Please try rephrasing."
    else:
        context_text = "\n---\n".join([item['content'] for item in search_results])
        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in existing_history])
        
        prompt = (
            "You are a helpful and precise AI assistant. Your task is to answer the user's 'Current Question' based *only* on the 'Retrieved Document Context'.\n"
            "Use the 'Chat History' to understand the conversational context (e.g., if the user asks 'why?'), but do not use it as a source for your answer. If the history is not relevant, ignore it.\n"
            "**Your answer must be based exclusively on the facts within the 'Retrieved Document Context'. Do not make up information.**\n\n"
            f"---BEGIN CHAT HISTORY---\n{history_text or 'No history yet.'}\n---END CHAT HISTORY---\n\n"
            f"---BEGIN RETRIEVED DOCUMENT CONTEXT---\n{context_text}\n---END RETRIEVED DOCUMENT CONTEXT---\n\n"
            f"**Current Question:** {query}\n\n"
            "**Answer:**"
        )

        try:
            answer = await call_llm(prompt=prompt)
        except Exception as e:
            logger.error(f"Chat generation failed: {e}")

    if not answer:
        raise HTTPException(status_code=500, detail="All AI models failed to generate a response.")

    # 5. Append to history and save to DB
    new_history = existing_history + [{"role": "user", "content": query}, {"role": "ai", "content": answer}]
    
    try:
        if session_id:
            # Session exists, UPDATE it
            supabase_client.table('chat_sessions').update({"chat_history": new_history, "last_updated": "now()"}).eq('session_id', session_id).execute()
            session_id_to_return = session_id
        else:
            # No session exists, INSERT a new one
            session_id_to_return = str(uuid.uuid4())
            supabase_client.table('chat_sessions').insert({
                "session_id": session_id_to_return,
                "document_id": doc_id,
                "user_id": user_id,
                "chat_history": new_history
            }).execute()
        logger.info(f"Chat history saved for session {session_id_to_return}")
    except Exception as e:
        logger.error(f"Failed to save chat history: {e}")
        traceback.print_exc() # Log the full error but don't crash
        # The user still gets their answer even if saving fails.
    
    return {"session_id": session_id_to_return, "chat_session": new_history, "current_answer": answer}