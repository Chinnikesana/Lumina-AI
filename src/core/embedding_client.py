"""
Centralized Embedding Client for Lumina AI Tutor
Uses Hugging Face Inference API (free tier) to generate embeddings.
Replaces the local sentence-transformers + PyTorch installation (~700MB savings).
"""

import asyncio
from typing import List
import httpx
from .config import settings
from .logger import get_logger

logger = get_logger(__name__)

# --- Configuration ---
HF_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
HF_API_URL = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{HF_MODEL_ID}"
EMBEDDING_DIMENSION = 384  # Must match the vector(384) in your Supabase schema


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a list of texts using the Hugging Face Inference API.

    This is a drop-in replacement for the local SentenceTransformer model.
    It produces identical 384-dimensional vectors using the same model,
    but runs remotely on Hugging Face's servers.

    Args:
        texts: A list of text strings to embed.

    Returns:
        A list of embedding vectors (each is a list of 384 floats).

    Raises:
        Exception: If the Hugging Face API call fails.
    """
    if not texts:
        return []

    headers = {"Authorization": f"Bearer {settings.HF_API_KEY}"}

    # HuggingFace Inference API accepts batches of texts
    # Process in batches of 64 to avoid payload size limits
    all_embeddings = []
    batch_size = 64

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        logger.info(f"Embedding batch {i // batch_size + 1}: {len(batch)} texts...")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    HF_API_URL,
                    headers=headers,
                    json={"inputs": batch, "options": {"wait_for_model": True}},
                )
                response.raise_for_status()
                batch_embeddings = response.json()

                # The API returns a list of embeddings.
                # For sentence-transformers models, each embedding may be nested
                # (token-level). We need to handle mean-pooling if needed.
                processed = []
                for emb in batch_embeddings:
                    if isinstance(emb, list) and len(emb) > 0:
                        if isinstance(emb[0], list):
                            # Token-level embeddings returned — mean pool them
                            import numpy as np
                            pooled = [sum(x) / len(x) for x in zip(*emb)]
                            processed.append(pooled)
                        else:
                            # Already a single vector
                            processed.append(emb)
                    else:
                        raise ValueError(f"Unexpected embedding format: {type(emb)}")

                all_embeddings.extend(processed)
                logger.info(f"Embedding batch {i // batch_size + 1}: Done ({len(processed)} vectors).")

        except httpx.HTTPStatusError as e:
            logger.error(f"HuggingFace API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"HuggingFace Inference API failed: {e.response.text}")
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise

    return all_embeddings


async def get_single_embedding(text: str) -> List[float]:
    """
    Generate an embedding for a single text string.
    Convenience wrapper around get_embeddings().

    Args:
        text: A single text string to embed.

    Returns:
        A single embedding vector (list of 384 floats).
    """
    embeddings = await get_embeddings([text])
    return embeddings[0]
