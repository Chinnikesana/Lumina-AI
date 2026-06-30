"""
Document Processing Service using LangGraph
Handles the complete document processing pipeline with AI agents
"""

import asyncio
import json
import uuid
import base64
from typing import Dict, List, Any, Optional, AsyncGenerator
from pathlib import Path
import aiofiles
import fitz  # PyMuPDF
import spacy
from typing import Tuple
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from ..core.logger import get_logger
from ..core.supabase_client import supabase_client
from ..core.config import settings
from ..models.models import DocumentStatus, NarrationStatus
from .tts_service import tts_service

logger = get_logger(__name__)

# Initialize spaCy model
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    logger.warning("spaCy model not found. Install with: python -m spacy download en_core_web_sm")
    nlp = None

# Try optional spaCy-Layout integration (fallback to PyMuPDF if unavailable)
try:
    # Placeholder import; replace with the actual spaCy-Layout API if available
    from spacy_layout import analyze_pdf as spacy_layout_analyze_pdf  # type: ignore
    HAS_SPACY_LAYOUT = True
except Exception:
    HAS_SPACY_LAYOUT = False

# Initialize Gemini 2.5 Flash (1M context)
llm_gemini_flash = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    max_output_tokens=8192,
    convert_system_message_to_human=True,
    google_api_key=settings.GOOGLE_API_KEY
)

llm_gemini_pro=ChatGoogleGenerativeAI(
    model="gemini-2.5-pro",
    temperature=0.7,
    max_output_tokens=8192,
    convert_system_message_to_human=True,
    google_api_key=settings.GOOGLE_API_KEY
)

# Document Processing State
class DocumentProcessingState:
    def __init__(self):
        self.document_id: str = ""
        self.document_path: str = ""
        self.narration_type: str = "simple"
        self.user_input: Optional[str] = None
        self.parsed_content: Dict[str, Any] = {}
        self.bounding_box_index: Dict[str, Any] = {}
        self.overview_narration: str = ""
        self.narration_chunks: List[Dict[str, Any]] = []
        self.current_chunk_index: int = 0
        self.context_summary: str = ""
        self.processing_stage: str = "initializing"

# Prompt Templates
OVERVIEW_NARRATION_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    SystemMessage(content="""You are an expert summarizer and educator. Your task is to create a concise, engaging overview of a document that will serve as an introduction to an interactive learning session.

Guidelines:
- Keep the overview to 2-3 sentences (aiming for 5-10 seconds of speech)
- Focus on the main themes, purpose, and key takeaways
- Use clear, accessible language
- Make it engaging and set expectations for the learning session
- Avoid technical jargon unless necessary

The overview should give learners a clear understanding of what they're about to learn and why it's important."""),
    HumanMessage(content="""Please create a concise overview for the following document:

Document Content:
{document_content}

User Instructions: {user_input}

Create an engaging 2-3 sentence overview that introduces the main themes and purpose of this document.""")
])

DETAILED_EXPLANATION_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    SystemMessage(content="""You are a detailed academic teacher and expert in document analysis. Your task is to create comprehensive, educational explanations of document sections with precise bounding box references.

Guidelines:
- Provide detailed explanations that build understanding step by step
- For each point you explain, reference specific text segments by their IDs
- Use the provided text segment IDs to indicate which parts should be highlighted
- Create multiple transcript segments for better synchronization
- Each segment should be 1-3 sentences and focus on a specific concept
- Provide the most relevant text segment IDs for highlighting each point
- Include context from previous explanations for continuity

Output Format (JSON):
{{
  "chunk_no": 1,
  "segments": [
    {{
      "transcript_id": "T1",
      "transcript_text": "Here comes the first explanation point.",
      "highlight_bounding_box_ids": ["p1_b1_id", "p1_b2_id"],
      "scroll_to_bounding_box_id": "p1_b1_id",
      "estimated_duration_ms": 3500
    }}
  ],
  "context_summary_for_next_chunk": "Brief summary for continuity"
}}"""),
    HumanMessage(content="""Please analyze and explain the following document section:

Current Text Chunk:
{current_text_chunk}

Previous Context: {previous_context}

User Instructions: {user_input}

Narration Type: {narration_type}

Generate a detailed explanation with precise bounding box references. Focus on making complex concepts accessible and engaging.""")
])

class DocumentProcessingService:
    def __init__(self):
        self.state = DocumentProcessingState()
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for document processing"""
        workflow = StateGraph(DocumentProcessingState)
        
        # Add nodes
        workflow.add_node("parse_document", self._parse_document_node)
        workflow.add_node("generate_overview", self._generate_overview_node)
        workflow.add_node("generate_detailed_narration", self._generate_detailed_narration_node)
        workflow.add_node("save_narration", self._save_narration_node)
        
        # Define the flow
        workflow.set_entry_point("parse_document")
        workflow.add_edge("parse_document", "generate_overview")
        workflow.add_edge("generate_overview", "generate_detailed_narration")
        workflow.add_edge("generate_detailed_narration", "save_narration")
        workflow.add_edge("save_narration", END)
        
        return workflow.compile()

    async def generate_overview_only(
        self,
        document_id: str,
        document_path: str,
        narration_type: str = "simple",
        user_input: Optional[str] = None,
    ) -> tuple[str, int]:
        """Parse and generate only the overview. Returns (overview_text, duration_ms)."""
        print(f"[generate_overview_only] document_id={document_id}")
        try:
            # Prepare state
            self.state = DocumentProcessingState()
            self.state.document_id = document_id
            self.state.document_path = document_path
            self.state.narration_type = narration_type
            self.state.user_input = user_input

            # Parse
            print("[generate_overview_only] Parsing start")
            await self._parse_document_node(self.state)
            print("[generate_overview_only] Parsing done, segments:", len(self.state.parsed_content.get("text_segments", [])))

            # Overview
            print("[generate_overview_only] Overview generation start")
            await self._generate_overview_node(self.state)
            print("[generate_overview_only] Overview generation done, length:", len(self.state.overview_narration))

            duration_ms = len(self.state.overview_narration.split()) * 200
            return self.state.overview_narration, duration_ms
        except Exception as e:
            logger.error(f"generate_overview_only failed: {e}")
            raise

    async def stream_chunks_only(
        self,
        document_id: str,
        document_path: str,
        narration_type: str = "simple",
        user_input: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Parse, generate overview, then generate chunks and yield SSE-friendly events."""
        print(f"[stream_chunks_only] document_id={document_id}")
        # Prepare state
        self.state = DocumentProcessingState()
        self.state.document_id = document_id
        self.state.document_path = document_path
        self.state.narration_type = narration_type
        self.state.user_input = user_input

        try:
            # Update document status to processing
            supabase_client.table('documents').update({
                "status": DocumentStatus.PROCESSING.value
            }).eq('document_id', document_id).execute()

            # Parse
            print("[stream_chunks_only] Parsing start")
            await self._parse_document_node(self.state)
            print("[stream_chunks_only] Parsing done, segments:", len(self.state.parsed_content.get("text_segments", [])))

            # Overview
            print("[stream_chunks_only] Overview generation start")
            await self._generate_overview_node(self.state)
            print("[stream_chunks_only] Overview length:", len(self.state.overview_narration))

            # Yield overview immediately
            yield {
                "type": "overview",
                "narration_text": self.state.overview_narration,
                "duration": len(self.state.overview_narration.split()) * 200,
            }

            # Detailed chunks
            print("[stream_chunks_only] Detailed generation start")
            await self._generate_detailed_narration_node(self.state)
            print("[stream_chunks_only] Detailed chunks:", len(self.state.narration_chunks))

            chunk_no = 0
            for chunk in self.state.narration_chunks:
                chunk_no += 1
                event = {
                    "type": "narration_chunk",
                    "chunk": {**chunk, "chunk_no": chunk.get("chunk_no", chunk_no)},
                }
                print(f"[stream_chunks_only] Yield chunk #{chunk_no}")
                yield event

            # Completion
            supabase_client.table('documents').update({
                "status": DocumentStatus.COMPLETED.value
            }).eq('document_id', document_id).execute()
            yield {"type": "completion", "message": "Document processing completed successfully"}
        except Exception as e:
            logger.error(f"stream_chunks_only failed: {e}")
            yield {"type": "error", "message": f"Streaming failed: {str(e)}"}
            supabase_client.table('documents').update({
                "status": DocumentStatus.PENDING.value
            }).eq('document_id', document_id).execute()
    
    async def _parse_document_node(self, state: DocumentProcessingState) -> DocumentProcessingState:
        """Parse document and extract text with bounding boxes"""
        logger.info(f"Parsing document: {state.document_path}")
        state.processing_stage = "parsing"
        
        try:
            if HAS_SPACY_LAYOUT:
                # Use spaCy-Layout to analyze PDF and extract segments and bounding boxes
                logger.info("Using spaCy-Layout for parsing")
                layout = await asyncio.to_thread(spacy_layout_analyze_pdf, state.document_path)
                parsed_content = {
                    "pages": [],
                    "total_pages": len(layout.get("pages", [])),
                    "text_segments": []
                }
                bounding_box_index = {}
                segment_id_counter = 1
                for p_idx, page in enumerate(layout.get("pages", [])):
                    page_content = {
                        "page_number": p_idx + 1,
                        "text_blocks": [],
                        "images": []
                    }
                    for seg in page.get("segments", []):
                        if not seg.get("text"):
                            continue
                        bbox = seg.get("bbox", {})
                        segment_id = f"p{p_idx + 1}_b{segment_id_counter}"
                        text_segment = {
                            "id": segment_id,
                            "text": seg.get("text", ""),
                            "bbox": {
                                "x": bbox.get("x", 0),
                                "y": bbox.get("y", 0),
                                "width": bbox.get("width", 0),
                                "height": bbox.get("height", 0)
                            },
                            "page": p_idx + 1,
                            "font_size": seg.get("font_size", 0),
                            "font": seg.get("font", "")
                        }
                        page_content["text_blocks"].append(text_segment)
                        parsed_content["text_segments"].append(text_segment)
                        bounding_box_index[segment_id] = text_segment
                        segment_id_counter += 1
                    parsed_content["pages"].append(page_content)
            else:
                # Fallback to PyMuPDF
                print("Using PyMuPDF for parsing")
                doc = fitz.open(state.document_path)
                parsed_content = {
                    "pages": [],
                    "total_pages": len(doc),
                    "text_segments": []
                }
                
                bounding_box_index = {}
                segment_id_counter = 1
                
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    page_content = {
                        "page_number": page_num + 1,
                        "text_blocks": [],
                        "images": []
                    }
                    
                    # Extract text blocks with bounding boxes
                    text_dict = page.get_text("dict")
                    
                    for block in text_dict["blocks"]:
                        if "lines" in block:  # Text block
                            for line in block["lines"]:
                                for span in line["spans"]:
                                    if span["text"].strip():
                                        bbox = span["bbox"]
                                        segment_id = f"p{page_num + 1}_b{segment_id_counter}"
                                        
                                        text_segment = {
                                            "id": segment_id,
                                            "text": span["text"],
                                            "bbox": {
                                                "x": bbox[0],
                                                "y": bbox[1],
                                                "width": bbox[2] - bbox[0],
                                                "height": bbox[3] - bbox[1]
                                            },
                                            "page": page_num + 1,
                                            "font_size": span["size"],
                                            "font": span["font"]
                                        }
                                        
                                        page_content["text_blocks"].append(text_segment)
                                        parsed_content["text_segments"].append(text_segment)
                                        bounding_box_index[segment_id] = text_segment
                                        segment_id_counter += 1
                    
                    parsed_content["pages"].append(page_content)
                
                doc.close()
            
            state.parsed_content = parsed_content
            state.bounding_box_index = bounding_box_index
            
            logger.info(f"Document parsed successfully: {len(parsed_content['text_segments'])} text segments found")
            
        except Exception as e:
            logger.error(f"Error parsing document: {str(e)}")
            raise
        
        return state
    
    async def _generate_overview_node(self, state: DocumentProcessingState) -> DocumentProcessingState:
        """Generate overview narration using Gemini 2.5 Pro"""
        logger.info("Generating overview narration")
        state.processing_stage = "generating_overview"
        
        try:
            # Use ALL parsed content to maximize context
            if not state.parsed_content:
                raise ValueError("Parsed content is empty before overview generation.")
            document_text = " ".join([seg["text"] for seg in state.parsed_content.get("text_segments", [])])
            if not document_text.strip():
                raise ValueError("Parsed document text is empty before overview generation.")
            print("document text len:", len(document_text))

            # --- FIX 2B: Add JSON instruction for clean output and use a simpler prompt ---
            # Modify the prompt for a clean, non-conversational output
            prompt_content = f"""
            You are an expert summarizer and educator. Your task is to create a concise, engaging overview of a document that will serve as an introduction to an interactive learning session.

Guidelines:
- Keep the overview to 2-3 sentences (aiming for 5-10 seconds of speech)
- Focus on the main themes, purpose, and key takeaways
- Use clear, accessible language
- Make it engaging and set expectations for the learning session
- Avoid technical jargon unless necessary
            
            Document Content (First part):
            ---
            {document_text.strip()}
            ---
            
            User Instructions: {state.user_input or 'No specific instructions provided'}
            
            Your output MUST be a valid JSON object with a single key: "overview_text".
            Example: {{"overview_text": "This document introduces the ReAct SQL Agent architecture..."}}
            """

            response = await llm_gemini_flash.ainvoke([HumanMessage(content=prompt_content)])

            # --- FIX 2C: Clean markdown/JSON fences before JSON parse ---
            try:
                cleaned = response.content.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[len("```json"):].strip()
                elif cleaned.startswith("```"):
                    cleaned = cleaned[len("```"):].strip()
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3].strip()

                overview_data = json.loads(cleaned)
                state.overview_narration = overview_data.get("overview_text", cleaned).strip()
                logger.info("Successfully extracted JSON overview_text.")
            except json.JSONDecodeError:
                # Fallback if the content wasn't valid JSON (use raw text and log warning)
                state.overview_narration = response.content.strip()
                logger.warning(f"Failed to parse overview JSON, using raw text output: {response.content[:80]}...")
                
            logger.info(f"Overview narration generated: {len(state.overview_narration)} characters")
            
        except Exception as e:
            logger.error(f"Error generating overview: {str(e)}")
            # Raise an informative error to stop processing
            raise RuntimeError(f"Overview generation failed: {e}")
        
        return state


    async def _generate_detailed_narration_node(self, state: DocumentProcessingState) -> DocumentProcessingState:
        """Generate detailed narration chunks using Gemini 2.5 Pro"""
        logger.info("Generating detailed narration")
        state.processing_stage = "generating_detailed_narration"
        
        try:
            # Split document into chunks for processing
            text_segments = state.parsed_content["text_segments"]
            chunk_size = 20  # Process 20 text segments at a time
            
            narration_chunks = []
            context_summary = state.overview_narration
            
            for i in range(0, len(text_segments), chunk_size):
                chunk_segments = text_segments[i:i + chunk_size]
                chunk_text = " ".join([seg["text"] for seg in chunk_segments])
                
                # Generate detailed explanation for this chunk
                prompt = DETAILED_EXPLANATION_PROMPT_TEMPLATE.format_messages(
                    current_text_chunk=chunk_text,
                    previous_context=context_summary,
                    user_input=state.user_input or "No specific instructions provided",
                    narration_type=state.narration_type
                )
                
                response = await llm_gemini_pro.ainvoke(prompt)
                
                try:
                    # Parse JSON response
                    narration_data = json.loads(response.content)
                    narration_chunks.append(narration_data)
                    
                    # Update context for next chunk
                    context_summary = narration_data.get("context_summary_for_next_chunk", context_summary)
                    
                    logger.info(f"Generated narration chunk {len(narration_chunks)}: {len(narration_data.get('segments', []))} segments")
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing LLM response as JSON: {str(e)}")
                    # Fallback: create a simple narration chunk
                    fallback_chunk = {
                        "chunk_no": len(narration_chunks) + 1,
                        "segments": [{
                            "transcript_id": f"T{len(narration_chunks) + 1}",
                            "transcript_text": chunk_text[:200] + "...",
                            "highlight_bounding_box_ids": [seg["id"] for seg in chunk_segments[:3]],
                            "scroll_to_bounding_box_id": chunk_segments[0]["id"] if chunk_segments else "",
                            "estimated_duration_ms": 3000
                        }],
                        "context_summary_for_next_chunk": "Continuing document analysis"
                    }
                    narration_chunks.append(fallback_chunk)
            
            state.narration_chunks = narration_chunks
            logger.info(f"Generated {len(narration_chunks)} narration chunks")
            
        except Exception as e:
            logger.error(f"Error generating detailed narration: {str(e)}")
            raise
        
        return state
    
    async def _save_narration_node(self, state: DocumentProcessingState) -> DocumentProcessingState:
        """Save narration data to database"""
        logger.info("Saving narration to database")
        state.processing_stage = "saving"
            # Prepare narration data in the required format
        try:
            narration_bbox_data = {
                "overview": {
                    "transcript_text": state.overview_narration,
                    "duration": len(state.overview_narration.split()) * 200  # Rough estimate: 200ms per word
                },
                "narrations": state.narration_chunks
            }
            
            # Create narration record in Supabase
            narration_data = {
                "document_id": state.document_id,
                "context": state.overview_narration,
                "narration_bbox": narration_bbox_data,
                "status": NarrationStatus.COMPLETED.value
            }
            
            response = supabase_client.table('narrations').insert(narration_data).execute()
            
            if not response.data:
                raise Exception("Failed to save narration to database")
            
            # Update document status
            supabase_client.table('documents').update({
                "status": DocumentStatus.COMPLETED.value
            }).eq('document_id', state.document_id).execute()
            
            logger.info(f"Narration saved successfully for document {state.document_id}")
            
        except Exception as e:
            logger.error(f"Error saving narration: {str(e)}")
            # Update document status to indicate error
            supabase_client.table('documents').update({
                "status": DocumentStatus.PENDING.value  # Reset to pending for retry
            }).eq('document_id', state.document_id).execute()
            raise
        
        return state
    
    async def process_document(
        self, 
        document_id: str, 
        document_path: str, 
        narration_type: str = "simple",
        user_input: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process a document through the complete pipeline
        
        Yields progress updates for real-time frontend updates
        """
        # Initialize state
        self.state.document_id = document_id
        self.state.document_path = document_path
        self.state.narration_type = narration_type
        self.state.user_input = user_input
        
        try:
            # Update document status to processing
            supabase_client.table('documents').update({
                "status": DocumentStatus.PROCESSING.value
            }).eq('document_id', document_id).execute()
            
            yield {
                "type": "status_update",
                "stage": "initializing",
                "message": "Starting document processing..."
            }
            
            # Run the graph
            final_state = await self.graph.ainvoke(self.state)
            
            # Stream overview immediately when ready
            if final_state.overview_narration:
                yield {
                    "type": "overview",
                    "narration_text": final_state.overview_narration,
                    "duration": len(final_state.overview_narration.split()) * 200
                }
            
            # Stream detailed narration chunks
            for chunk in final_state.narration_chunks:
                for segment in chunk.get("segments", []):
                    # Generate audio for the segment
                    audio_data = await tts_service.generate_audio(segment["transcript_text"])
                    
                    segment_data = {
                        "type": "narration_segment",
                        "segment": segment,
                        "chunk_no": chunk.get("chunk_no", 0),
                        "audio_data": base64.b64encode(audio_data).decode() if audio_data else None
                    }
                    
                    yield segment_data
            
            yield {
                "type": "completion",
                "message": "Document processing completed successfully"
            }
            
        except Exception as e:
            logger.error(f"Document processing failed: {str(e)}")
            yield {
                "type": "error",
                "message": f"Processing failed: {str(e)}"
            }
            
            # Update document status to indicate error
            supabase_client.table('documents').update({
                "status": DocumentStatus.PENDING.value
            }).eq('document_id', document_id).execute()

# Global service instance
document_processing_service = DocumentProcessingService()
