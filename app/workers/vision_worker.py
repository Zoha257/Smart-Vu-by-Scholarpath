"""
app/workers/vision_worker.py — Section 15.3
Standalone-callable wrapper around the Vision LLM escalation stage
(Section 8.3, 20.5 — only invoked when OCR confidence is insufficient).
"""
from app.ai_clients.vision_llm_client import explain_visual
from app.core.logging import logger


async def process_job(image_url: str, ocr_text_so_far: str = "") -> str:
    logger.info(f"vision_worker_job_start image_url={image_url}")
    result = await explain_visual(image_url=image_url, ocr_text_so_far=ocr_text_so_far)
    logger.info("vision_worker_job_done")
    return result
