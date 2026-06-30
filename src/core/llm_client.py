"""
Centralized LLM Client for Lumina AI Tutor
Uses Groq (primary) and OpenRouter (fallback) via the OpenAI-compatible SDK.
No LangChain dependency required.
"""

import asyncio
import json
from typing import Optional, List, Dict, Any
from openai import OpenAI
from .config import settings
from .logger import get_logger

logger = get_logger(__name__)

# --- Groq Client (Primary) ---
groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=settings.GROQ_API_KEY,
)

# --- OpenRouter Client (Fallback) ---
OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY or settings.OPENROUTER_API_KEY2
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://lumina.ai",
    "X-Title": "Lumina AI Tutor",
}

# --- Model Configurations ---
# Primary: Groq free tier
GROQ_PRIMARY_MODEL = "llama-3.3-70b-versatile"

# Fallback chain: OpenRouter free models
OPENROUTER_FALLBACK_MODELS = [
    {"name": "deepseek-v3", "model": "deepseek/deepseek-chat-v3.1:free"},
    {"name": "gemini-flash", "model": "google/gemini-2.0-flash-exp:free"},
    {"name": "chimera", "model": "tngtech/deepseek-r1t2-chimera:free"},
]


async def call_llm(
    prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 8192,
    system_message: Optional[str] = None,
    json_mode: bool = False,
) -> str:
    """
    Call an LLM with automatic fallback chain:
    1. Groq (llama-3.3-70b-versatile)
    2. OpenRouter fallback models

    Args:
        prompt: The user prompt to send.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in the response.
        system_message: Optional system message.
        json_mode: If True, request JSON output format.

    Returns:
        The LLM's text response content.

    Raises:
        Exception: If all models in the fallback chain fail.
    """
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    extra_kwargs = {}
    if json_mode:
        extra_kwargs["response_format"] = {"type": "json_object"}

    # --- Attempt 1: Groq ---
    try:
        logger.info(f"LLM call: Attempting Groq ({GROQ_PRIMARY_MODEL})...")

        def _call_groq():
            return groq_client.chat.completions.create(
                model=GROQ_PRIMARY_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra_kwargs,
            )

        completion = await asyncio.to_thread(_call_groq)
        content = completion.choices[0].message.content
        if content:
            logger.info(f"LLM call: Groq succeeded ({len(content)} chars).")
            return content
        else:
            logger.warning("LLM call: Groq returned empty content.")
    except Exception as e:
        logger.warning(f"LLM call: Groq failed: {e}. Trying fallbacks...")

    # --- Attempts 2+: OpenRouter Fallbacks ---
    for model_info in OPENROUTER_FALLBACK_MODELS:
        try:
            model_name = model_info["name"]
            logger.info(f"LLM call: Attempting OpenRouter ({model_name})...")

            def _call_openrouter(mi=model_info):
                return openrouter_client.chat.completions.create(
                    extra_headers=OPENROUTER_HEADERS,
                    model=mi["model"],
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra_kwargs,
                )

            completion = await asyncio.to_thread(_call_openrouter)
            content = completion.choices[0].message.content
            if content:
                logger.info(f"LLM call: OpenRouter ({model_name}) succeeded ({len(content)} chars).")
                return content
            else:
                logger.warning(f"LLM call: OpenRouter ({model_name}) returned empty content.")
        except Exception as e:
            logger.warning(f"LLM call: OpenRouter ({model_name}) failed: {e}.")

    raise Exception("All LLM models in the fallback chain failed to generate a response.")


def parse_json_response(text: str) -> Any:
    """
    Robustly parse a JSON response from an LLM, stripping markdown fences.

    Args:
        text: Raw LLM response text that may contain ```json ... ``` wrappers.

    Returns:
        Parsed Python object (dict or list).

    Raises:
        json.JSONDecodeError: If the text cannot be parsed as JSON.
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
        # Find the last </think> and take everything after it
        think_end = cleaned.rfind("</think>")
        if think_end != -1:
            cleaned = cleaned[think_end + len("</think>"):].strip()
            # Re-strip markdown fences if present after think block
            if cleaned.startswith("```json"):
                cleaned = cleaned[len("```json"):].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[len("```"):].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

    return json.loads(cleaned)
