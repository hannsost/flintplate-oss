"""Sentence-transformers embedding service – Sprint 0.4.

Model: all-MiniLM-L6-v2 (384 dimensions, ~80 MB, runs on CPU)
Lazy-loaded singleton to avoid startup cost.
"""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)

_model: Any = None  # SentenceTransformer instance, loaded on first use
_MODEL_NAME = "all-MiniLM-L6-v2"


_EMBED_DIM = 384
_model_unavailable = False  # set to True permanently after first load failure
_model_lock = Lock()


def _load_model() -> Any:
    global _model, _model_unavailable
    if _model_unavailable:
        return None
    with _model_lock:
        if _model is not None or _model_unavailable:
            return _model
        try:
            from sentence_transformers import SentenceTransformer

            log.info("Loading embedding model %s …", _MODEL_NAME)
            # Provision models explicitly; a page request must never download one.
            _model = SentenceTransformer(_MODEL_NAME, local_files_only=True)
            log.info("Embedding model loaded.")
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            log.warning("Embedding model unavailable (%s) – falling back to zero vectors", exc)
            _model_unavailable = True
            return None
    return _model


def _embed_sync(texts: list[str]) -> list[list[float]]:
    model = _load_model()
    if model is None:
        # No sentence-transformers available – return zero vectors so callers still work
        return [[0.0] * _EMBED_DIM for _ in texts]
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Async wrapper — runs in thread pool to avoid blocking the event loop."""
    if not texts:
        return []
    from app.config import get_settings

    if get_settings().ai_mock_mode:
        return [[0.0] * _EMBED_DIM for _ in texts]
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_job(title: str, description: str | None) -> list[float]:
    """Embed a single job posting (title + description)."""
    text = f"{title}. {description or ''}".strip()
    vectors = await embed_texts([text])
    return vectors[0]


async def embed_profile(
    headline: str | None,
    summary: str | None,
    skills: list[str],
) -> list[float]:
    """Embed a candidate profile for matching."""
    parts = []
    if headline:
        parts.append(headline)
    if summary:
        parts.append(summary)
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    text = ". ".join(parts) or "candidate profile"
    vectors = await embed_texts([text])
    return vectors[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two normalized vectors (dot product)."""
    return float(sum(x * y for x, y in zip(a, b, strict=True)))
