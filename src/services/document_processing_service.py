import os
import asyncio
import json
import traceback
from typing import Dict, List, Any, Optional, AsyncGenerator

import fitz  # PyMuPDF

from ..core.logger import get_logger
from ..core.supabase_client import supabase_client
from ..core.config import settings
from ..core.llm_client import call_llm, parse_json_response
from ..core.embedding_client import get_embeddings

logger = get_logger(__name__)

# --- 1. LLM Prompts & Setup ---

SAFE_TOKEN_LIMIT = 163800 * 0.85

def build_simple_prompt(context: Optional[str], chunk: Dict[str, Any], clean_text_input: str, user_input: Optional[str]) -> str:
    return (
        "You are an efficient and clear guide. Your goal is to provide a **brief, high-level summary** of a document section. "
        "Your response MUST be a single, valid JSON object.\n\n"
        f"**Previous Context:** We just covered: '{context or 'the beginning of the document.'}'\n\n"
        f"**Current Section to Explain:** '{chunk['section_title']}'\n"
        f"**Content of this section:**\n---\n{clean_text_input}\n---\n\n"
        f"**User's Custom Instructions:** {user_input or 'Provide a simple summary.'}\n\n"
        "--- YOUR TEACHING PLAN (SIMPLE) ---\n"
        "1.  **Summarize, Don't Elaborate:** Create one, maximum two, narration segments that summarize the entire content chunk.\n"
        "2.  **Handle Content Briefly:** For tables/formulas, mention topic briefly; for text, give a one-sentence main point.\n"
        "3.  **Broad Highlighting:** In `highlight_ids`, include all segment IDs from the content summarized.\n"
        "4.  **Provide a Simple Context Summary:** Add `context_summary_for_next_chunk`.\n\n"
        "--- REQUIRED JSON OUTPUT FORMAT ---\n"
        "{{\n"
        "  \"narration_segments\": [\n"
        "    {\"transcript_text\": \"This section provides a high-level summary of...\", \"highlight_ids\": [\"seg_1\", \"seg_2\"]}\n"
        "  ],\n"
        "  \"context_summary_for_next_chunk\": \"We just summarized the section.\"\n"
        "}}"
    )

def build_detailed_prompt(context: Optional[str], chunk: Dict[str, Any], clean_text_input: str, user_input: Optional[str]) -> str:
    return (
        "You are an expert and friendly tutor. Explain the section clearly and engagingly. "
        "Your response MUST be a single, valid JSON object.\n\n"
        f"**Previous Context:** We just finished discussing: '{context or 'the beginning of the document.'}'\n\n"
        f"**Current Section to Explain:** '{chunk['section_title']}'\n"
        f"**Content of this section:**\n---\n{clean_text_input}\n---\n\n"
        f"**User's Custom Instructions:** {user_input or 'Explain clearly and in detail.'}\n\n"
        "--- YOUR TEACHING PLAN (DETAILED) ---\n"
        "1.  **Start with a Transition:** Begin with a friendly, conversational sentence that connects to the 'Previous Context'.\n"
        "2.  **Explain, Don't Just Read:** Teach the meaning, purpose, and importance of the info.\n"
        "3.  **Handle Content Types Intelligently:** (Tables, Formulas, Concepts, Lists).\n"
        "4.  **Use Intelligent Highlighting:** Selectively use `highlight_ids`.\n"
        "5.  **Summarize for Continuity:** Conclude with `context_summary_for_next_chunk`.\n\n"
        "--- REQUIRED JSON OUTPUT FORMAT ---\n"
        "{{\n"
        "  \"narration_segments\": [\n"
        "    {\"transcript_text\": \"...\", \"highlight_ids\": [\"...\"]}\n"
        "  ],\n"
        "  \"context_summary_for_next_chunk\": \"...\"\n"
        "}}"
    )

# --- 2. Pipeline Functions (Replaces LangGraph) ---

async def parse_document(document_id: str, local_path: str) -> Dict[str, Any]:
    """Parses text blocks and coordinates from the document using PyMuPDF."""
    logger.info(f"parse_document: Starting for path: {local_path} with PyMuPDF")
    try:
        def _parse():
            doc = fitz.open(local_path)
            
            all_segments = []
            bbox_index = {}
            counter = 1
            full_markdown_parts = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Extract text blocks
                # format: (x0, y0, x1, y1, "lines in block", block_no, block_type)
                # block_type 0 = text, 1 = image
                blocks = page.get_text("blocks")
                
                # Sort blocks by y coordinate, then x coordinate
                blocks.sort(key=lambda b: (b[1], b[0]))
                
                for b in blocks:
                    # Ignore images
                    if b[-1] == 1:
                        continue
                    
                    text = b[4].strip()
                    if not text:
                        continue
                        
                    x0, y0, x1, y1 = b[:4]
                    width = x1 - x0
                    height = y1 - y0
                    
                    seg_id = f"seg_{counter}"
                    bbox = {
                        "x": x0, 
                        "y": y0, 
                        "width": width, 
                        "height": height, 
                        "page_no": page_num + 1
                    }
                    
                    segment = {
                        "id": seg_id, 
                        "text": text, 
                        "label": "text", 
                        "bbox": bbox
                    }
                    
                    all_segments.append(segment)
                    bbox_index[seg_id] = segment
                    counter += 1
                    full_markdown_parts.append(text)
            
            # Save raw text as markdown representation
            markdown_text = "\n\n".join(full_markdown_parts)
            if markdown_text:
                supabase_client.table('documents').update({
                    'doc_content': markdown_text
                }).eq('document_id', document_id).execute()
                logger.info(f"Saved markdown content ({len(markdown_text)} chars) to documents table.")
                
            doc.close()
            return {"text_segments": all_segments, "bounding_box_index": bbox_index}

        parsed_data = await asyncio.to_thread(_parse)
        logger.info(f"Successfully parsed {len(parsed_data['text_segments'])} segments using PyMuPDF.")
        return parsed_data
    except Exception as e:
        logger.error(f"CRITICAL FAILURE in parse_document: {e}")
        traceback.print_exc()
        raise

async def generate_overview(parsed_data: Dict[str, Any], user_input: Optional[str]) -> str:
    """Generates the document overview."""
    logger.info("Calling LLM for summary overview...")
    full_text = " ".join(seg["text"] for seg in parsed_data["text_segments"])
    prompt = f"""
    You are an expert educator and a friendly guide. Read the document text below and create a short, welcoming overview. 
    It needs to be simple, engaging, and set the stage for the lesson.
    Keep it Concise: The entire overview should only be 2-3 sentences long.
    
    User's Custom Instructions:
    {user_input}

    Full Document Text:
    {full_text}
    
    Your Task:
    Based on the text and guidelines, generate the overview. You MUST respond ONLY with a valid JSON object in the following format:
    {{"overview_text": "Your friendly 2-3 sentence overview goes here."}}
    """
    
    try:
        response_text = await call_llm(prompt, temperature=0.4, json_mode=True)
        overview_data = parse_json_response(response_text)
        return overview_data.get("overview_text", "Overview generation failed.")
    except Exception as e:
        logger.warning(f"Failed to generate overview, returning raw LLM error: {e}")
        return "Failed to generate overview."

def persist_initial_state(document_id: str, parsed_data: Dict[str, Any], overview_text: str) -> Dict[str, Any]:
    """Groups data into chunks and saves state to Supabase."""
    logger.info(f"Saving state for doc_id: {document_id}")
    
    final_chunks = []
    chunk_text, chunk_segs, chunk_title = "", [], None
    def token_estimate(chars: int) -> int: return int(chars * 0.25)

    for seg in parsed_data['text_segments']:
        seg_text = f'ID: {seg["id"]}, Text: {seg["text"]}\n'
        next_len = len(chunk_text) + len(seg_text)
        if token_estimate(next_len) > SAFE_TOKEN_LIMIT and chunk_segs:
            title = chunk_title or (chunk_segs[0]['text'][:60] + '...')
            final_chunks.append({"section_title": title, "segments": chunk_segs})
            chunk_text, chunk_segs, chunk_title = "", [], None
        if seg.get('label') in ['section_header', 'title'] and not chunk_title:
            chunk_title = seg['text']
        chunk_text += seg_text
        chunk_segs.append(seg)
        
    if chunk_segs:
        title = chunk_title or (chunk_segs[0]['text'][:60] + '...')
        final_chunks.append({"section_title": title, "segments": chunk_segs})

    overview_obj = {"transcript_text": overview_text, "duration": len(overview_text.split()) * 200}
    narration_bbox_payload = {"overview": overview_obj, "narrations": []}
    raw_data_payload = {
        "bounding_box_index": parsed_data.get("bounding_box_index", {}),
        "chunks_to_process": final_chunks,
        "processed_chunk_index": -1
    }
    
    supabase_client.table('narrations').insert({
        "document_id": document_id,
        "context": overview_text,
        "narration_bbox": narration_bbox_payload,
        "raw_data": raw_data_payload,
        "status": "processing"
    }).execute()
    
    return narration_bbox_payload

# --- 3. Main Service Class ---

def simple_text_splitter(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> List[str]:
    """Simple text splitter to replace langchain's RecursiveCharacterTextSplitter."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        
        # Adjust end to nearest newline or space if not at the end of the text
        if end < len(text):
            last_newline = text.rfind('\n', start, end)
            last_space = text.rfind(' ', start, end)
            if last_newline != -1 and last_newline > start + chunk_size // 2:
                end = last_newline
            elif last_space != -1 and last_space > start + chunk_size // 2:
                end = last_space
                
        chunks.append(text[start:end].strip())
        start = end - chunk_overlap
        if start >= end: # Prevent infinite loop
            start = end
    return [c for c in chunks if c]

class DocumentProcessingService:
    
    async def initial_processing(self, document_id: str, local_path: str, user_input: Optional[str] = None) -> Dict[str, Any]:
        """Runs the initial processing synchronously pipeline."""
        parsed_data = await parse_document(document_id, local_path)
        overview_text = await generate_overview(parsed_data, user_input)
        final_narration_output = persist_initial_state(document_id, parsed_data, overview_text)
        return final_narration_output

    async def stream_narration_chunks(self, document_id: str, user_id: str) -> AsyncGenerator[Dict, None]:
        """Loads state from `raw_data`, streams enriched chunks, and clears `raw_data` on completion."""
        narration_resp = supabase_client.table('narrations').select('narration_bbox, raw_data, context').eq('document_id', document_id).single().execute()
        if not narration_resp.data:
            yield {"type": "error", "message": "Narration state not found."}; return

        full_narration_bbox = narration_resp.data.get("narration_bbox", {})
        raw_data = narration_resp.data.get("raw_data")
        if not raw_data:
             yield {"type": "completion", "message": "Document already processed."}; return

        chunks_to_process = raw_data.get("chunks_to_process", [])
        last_processed_index = raw_data.get("processed_chunk_index", -1)
        bounding_box_index = raw_data.get("bounding_box_index", {})
        current_context = narration_resp.data.get("context")
        user_input_resp = supabase_client.table('documents').select('extra_input').eq('document_id', document_id).single().execute()
        user_input = user_input_resp.data.get('extra_input') if user_input_resp.data else None

        for i in range(last_processed_index + 1, len(chunks_to_process)):
            chunk = chunks_to_process[i]
            clean_text_input = "\n".join([f'ID: {seg["id"]}, Text: "{seg["text"].strip()}"' for seg in chunk['segments']])
            
            mode = (user_input or "").strip().lower()
            use_simple = mode == "simple"
            prompt_text = build_simple_prompt(current_context, chunk, clean_text_input, user_input) if use_simple else build_detailed_prompt(current_context, chunk, clean_text_input, user_input)
            
            try:
                response_text = await call_llm(prompt_text, json_mode=True)
                narration_result = parse_json_response(response_text)
            except Exception as e:
                logger.error(f"Failed to generate narration chunk {i}: {e}")
                yield {"type": "error", "message": f"Failed to generate chunk {i}"}
                return
            
            for seg in narration_result.get("narration_segments", []):
                seg["highlight_bboxes"] = [bounding_box_index.get(id) for id in seg.get("highlight_ids", []) if bounding_box_index.get(id)]
                if "scroll_to_id" not in seg or not seg["scroll_to_id"]:
                    highlight_ids = seg.get("highlight_ids", [])
                    seg["scroll_to_id"] = highlight_ids[0] if highlight_ids else None

            chunk_to_yield = {"chunk_no": i, **narration_result}
            yield {"type": "narration_chunk", "chunk": chunk_to_yield}

            current_context = narration_result.get("context_summary_for_next_chunk", current_context)
            full_narration_bbox['narrations'].append(chunk_to_yield)
            raw_data['processed_chunk_index'] = i
            
            supabase_client.table('narrations').update({
                "narration_bbox": full_narration_bbox, "raw_data": raw_data, "context": current_context
            }).eq('document_id', document_id).execute()
        
        logger.info(f"Finalizing document {document_id}. Clearing raw_data column.")
        supabase_client.table('narrations').update({"raw_data": None}).eq('document_id', document_id).execute()
        supabase_client.table('documents').update({"status": "completed"}).eq('document_id', document_id).execute()
        supabase_client.table('narrations').update({"status": "completed"}).eq('document_id', document_id).execute()
        yield {"type": "completion", "message": "Document processing completed successfully."}

    async def index_document_for_chat(self, document_id: str):
        """Asynchronous background task to split, embed, and store document content."""
        logger.info(f"Starting chat indexing for doc_id: {document_id}")
        try:
            doc_resp = supabase_client.table('documents').select('doc_content').eq('document_id', document_id).single().execute()
            
            if not doc_resp.data or not doc_resp.data.get('doc_content'):
                logger.error(f"Cannot index doc_id {document_id}: content not found.")
                return

            doc_content = doc_resp.data['doc_content']
            chunks = simple_text_splitter(doc_content, chunk_size=1000, chunk_overlap=100)
            
            if not chunks:
                logger.warning(f"No text chunks were produced for doc_id {document_id}. Skipping indexing.")
                return

            # Call HuggingFace Inference API for all chunks
            embeddings = await get_embeddings(chunks)

            rows_to_insert = [
                {"document_id": document_id, "content": chunk, "embedding": embedding}
                for chunk, embedding in zip(chunks, embeddings)
            ]
            
            supabase_client.table('document_chunks').insert(rows_to_insert).execute()
            logger.info(f"Successfully indexed {len(chunks)} chunks for doc_id: {document_id}")
            
        except Exception as e:
            logger.error(f"Chat indexing background task failed for doc_id {document_id}: {e}")
            traceback.print_exc()

document_processing_service = DocumentProcessingService()
