"""
app/ai_clients/vision_llm_client.py

Thin wrapper around the shared groq_client's describe_image() (Section 8.3).
Used ONLY when OCR confidence is insufficient or the visual is a diagram
requiring semantic understanding — never on every frame (Section 20.5).
"""
from app.ai_clients.groq_client import describe_image
from app.core.logging import logger

OCR_CONFIDENCE_ESCALATION_THRESHOLD = 0.55


async def explain_visual(image_url: str, ocr_text_so_far: str = "") -> str:
    """
    Asks the Vision LLM to describe/explain a keyframe that OCR could not
    read confidently. `image_url` must be a publicly reachable R2 URL (or a
    signed URL) since the Groq API fetches it directly.
    """
    prompt = (
        "You are analyzing a single frame from a university lecture video. "
        "Describe any board writing, diagrams, formulas, or code visible in "
        "the image, transcribing text as accurately as possible. "
        f"OCR partially read: {ocr_text_so_far!r} — correct or complete it "
        "where the image is clearer than the OCR output. "
        "Be factual; do not invent content that is not visibly present."
    )
    text, meta = await describe_image(
        image_url=image_url, prompt=prompt, feature="ingestion.vision_fallback"
    )
    logger.info(f"vision_llm_fallback_used latency_ms={meta['latency_ms']}")
    return text
