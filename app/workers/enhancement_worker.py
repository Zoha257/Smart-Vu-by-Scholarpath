"""
app/workers/enhancement_worker.py — Section 15.3
Standalone-callable wrapper around optional Real-ESRGAN enhancement
(Section 8.7, 20.3 — improves readability, never fabricates missing detail).
"""
from app.ai_clients.esrgan_pipeline import enhance_image
from app.core.logging import logger


def process_job(input_path: str, output_path: str) -> str:
    logger.info(f"enhancement_worker_job_start input={input_path}")
    result = enhance_image(input_path, output_path)
    logger.info(f"enhancement_worker_job_done output={result}")
    return result
