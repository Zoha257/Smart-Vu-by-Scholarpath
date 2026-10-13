"""
app/workers/embedding_worker.py — Section 15.3
Standalone-callable wrapper around the embedding stage (Section 8.5).
"""
from app.ai_clients.embedding_model import embed_texts
from app.core.logging import logger


def process_job(texts: list[str]) -> list[list[float]]:
    logger.info(f"embedding_worker_job_start count={len(texts)}")
    vectors = embed_texts(texts)
    logger.info(f"embedding_worker_job_done count={len(vectors)}")
    return vectors
