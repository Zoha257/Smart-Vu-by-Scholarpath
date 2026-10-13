"""
app/ai_clients/embedding_model.py

Local embedding model (Section 8.5) used for semantic retrieval. Runs
in-process via sentence-transformers — no external API key or cost, which
matters because embeddings are generated for every chunk of every lecture
(Admin App, at ingestion) and for every visitor query (Client App, live).

Both applications import this same module (Section 15.1 shared package).
"""
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()

_MODEL: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        logger.info(f"embedding_model_loaded name={settings.EMBEDDING_MODEL_NAME}")
    return _MODEL


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embeds a list of strings. Used at ingestion for every chunk."""
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    """Single-string embed — used by the Client App for a live search/RAG query."""
    return embed_texts([text])[0]
