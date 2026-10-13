"""
app/ingestion/uncertainty_handler.py

Visual uncertainty handling (Section 9.3): if the system cannot confidently
understand a visual section, it should capture additional nearby frames,
rerun OCR, use the Vision LLM if required, and preserve the uncertainty
state if the information remains unclear — never silently drop it or
fabricate a confident-looking answer.
"""
from dataclasses import dataclass

import cv2

from app.ai_clients.ocr_pipeline import run_ocr
from app.ai_clients.vision_llm_client import (
    OCR_CONFIDENCE_ESCALATION_THRESHOLD,
    explain_visual,
)
from app.core.logging import logger


@dataclass
class VisualResolution:
    text: str
    confidence: float
    vision_llm_used: bool
    still_uncertain: bool


async def resolve_visual(
    frame_path: str, video_path: str, timestamp: float, output_dir: str, r2_public_url: str
) -> VisualResolution:
    """
    Section 9.3 pipeline:
      1. Run OCR on the keyframe.
      2. If confidence is low, grab 1-2 nearby frames and retry OCR.
      3. If still low, escalate to the Vision LLM (Section 8.3, 20.5).
      4. If the Vision LLM output is also thin/uncertain, mark the asset as
         uncertain rather than pretending confidence we don't have.
    """
    ocr_result = run_ocr(frame_path)

    if ocr_result.confidence >= OCR_CONFIDENCE_ESCALATION_THRESHOLD:
        return VisualResolution(
            text=ocr_result.text,
            confidence=ocr_result.confidence,
            vision_llm_used=False,
            still_uncertain=False,
        )

    # Step 2 — try a nearby frame (+0.5s) in case of motion blur / transition
    nearby_path = _grab_frame_near(video_path, timestamp + 0.5, output_dir)
    if nearby_path:
        retry_result = run_ocr(nearby_path)
        if retry_result.confidence > ocr_result.confidence:
            ocr_result = retry_result

    if ocr_result.confidence >= OCR_CONFIDENCE_ESCALATION_THRESHOLD:
        return VisualResolution(
            text=ocr_result.text,
            confidence=ocr_result.confidence,
            vision_llm_used=False,
            still_uncertain=False,
        )

    # Step 3 — escalate to Vision LLM (expensive; used only here, Section 20.5)
    logger.info(f"visual_uncertain_escalating_to_vision_llm timestamp={timestamp}")
    vision_text = await explain_visual(image_url=r2_public_url, ocr_text_so_far=ocr_result.text)

    still_uncertain = len(vision_text.strip()) < 15  # heuristic: essentially empty
    return VisualResolution(
        text=vision_text or ocr_result.text,
        confidence=max(ocr_result.confidence, 0.5 if not still_uncertain else 0.2),
        vision_llm_used=True,
        still_uncertain=still_uncertain,
    )


def _grab_frame_near(video_path: str, timestamp: float, output_dir: str) -> str | None:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_number = int(timestamp * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    path = f"{output_dir}/frame_{timestamp:.2f}_retry.jpg"
    cv2.imwrite(path, frame)
    return path
