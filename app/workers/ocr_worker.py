"""
app/workers/ocr_worker.py — Section 15.3
Standalone-callable wrapper around the OCR stage (see transcription_worker.py
for the split-later rationale).
"""
from app.ai_clients.ocr_pipeline import OcrResult, run_ocr
from app.core.logging import logger


def process_job(image_path: str) -> OcrResult:
    logger.info(f"ocr_worker_job_start image={image_path}")
    result = run_ocr(image_path)
    logger.info(f"ocr_worker_job_done image={image_path} confidence={result.confidence}")
    return result
