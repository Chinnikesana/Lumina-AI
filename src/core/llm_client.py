import asyncio
import json
from typing import Optional, List, Dict, Any
from openai import OpenAI
import google.generativeai as genai
from .config import settings
from .logger import get_logger

logger = get_logger(__name__)

# --- Groq Client ---
groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=settings.GROQ_API_KEY,
)

groq_client_2 = None
if settings.GROQ_API_KEY_2:
    groq_client_2 = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=settings.GROQ_API_KEY_2,
    )

# --- Gemini Config ---
if settings.GOOGLE_API_KEY:
    genai.configure(api_key=settings.GOOGLE_API_KEY)

# --- Model Configurations ---
GROQ_PRIMARY_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-1.5-pro"

async def call_llm(
    prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 8192,
    system_message: Optional[str] = None,
    json_mode: bool = False,
    prefer_gemini: bool = False,
) -> str:
    """
    Call an LLM with automatic fallback chain:
    If prefer_gemini:
      1. Gemini (gemini-1.5-pro)
      2. Groq (Key 1 -> Key 2 -> Key 1)
    Else:
      1. Groq (Key 1 -> Key 2 -> Key 1)
    """
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    extra_kwargs = {}
    if json_mode:
        extra_kwargs["response_format"] = {"type": "json_object"}

    # Helper functions
    def _call_groq(client):
        return client.chat.completions.create(
            model=GROQ_PRIMARY_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra_kwargs,
        )

    def _call_gemini():
        model = genai.GenerativeModel(GEMINI_MODEL)
        full_prompt = f"{system_message}\n\n{prompt}" if system_message else prompt
        gen_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        response = model.generate_content(full_prompt, generation_config=gen_config)
        return response.text

    # --- Attempt Gemini if preferred ---
    if prefer_gemini and settings.GOOGLE_API_KEY:
        try:
            logger.info(f"LLM call: Attempting Gemini ({GEMINI_MODEL})...")
            content = await asyncio.to_thread(_call_gemini)
            if content:
                logger.info(f"LLM call: Gemini succeeded ({len(content)} chars).")
                return content
        except Exception as e:
            logger.warning(f"LLM call: Gemini failed: {e}. Falling back to Groq...")

    # --- Attempt 1: Groq (Key 1) ---
    try:
        logger.info(f"LLM call: Attempting Groq ({GROQ_PRIMARY_MODEL}) with Key 1...")
        completion = await asyncio.to_thread(_call_groq, groq_client)
        content = completion.choices[0].message.content
        if content:
            logger.info(f"LLM call: Groq (Key 1) succeeded ({len(content)} chars).")
            return content
        else:
            logger.warning("LLM call: Groq (Key 1) returned empty content.")
    except Exception as e:
        logger.warning(f"LLM call: Groq (Key 1) failed: {e}.")
        
        # --- Attempt 2: Groq (Key 2) ---
        if groq_client_2:
            try:
                logger.info(f"LLM call: Attempting Groq ({GROQ_PRIMARY_MODEL}) with Key 2...")
                completion = await asyncio.to_thread(_call_groq, groq_client_2)
                content = completion.choices[0].message.content
                if content:
                    logger.info(f"LLM call: Groq (Key 2) succeeded ({len(content)} chars).")
                    return content
                else:
                    logger.warning("LLM call: Groq (Key 2) returned empty content.")
            except Exception as e2:
                logger.warning(f"LLM call: Groq (Key 2) failed: {e2}. Falling back to Key 1...")
                
                # --- Attempt 3: Groq (Key 1 again) ---
                try:
                    logger.info(f"LLM call: Attempting Groq ({GROQ_PRIMARY_MODEL}) with Key 1 again...")
                    completion = await asyncio.to_thread(_call_groq, groq_client)
                    content = completion.choices[0].message.content
                    if content:
                        logger.info(f"LLM call: Groq (Key 1 again) succeeded ({len(content)} chars).")
                        return content
                except Exception as e3:
                    logger.warning(f"LLM call: Groq (Key 1 again) failed: {e3}.")
        else:
            logger.info("No second Groq API key available.")

    raise Exception("All LLM models in the fallback chain failed to generate a response.")


def parse_json_response(text: str) -> Any:
    """
    Robustly parse a JSON response from an LLM, stripping markdown fences.
    """
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    # Some models wrap in <think>...</think> tags — strip those too
    if "<think>" in cleaned:
        think_end = cleaned.rfind("</think>")
        if think_end != -1:
            cleaned = cleaned[think_end + len("</think>"):].strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[len("```json"):].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[len("```"):].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

    return json.loads(cleaned)

