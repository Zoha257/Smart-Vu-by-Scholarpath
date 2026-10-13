"""
app/ai_clients/ocr_pipeline.py

PaddleOCR wrapper (Section 8.6). Extracts visible text from slides, boards,
code, formulas, and labeled diagrams. Runs locally — no external API key.
"""
from dataclasses import dataclass

from paddleocr import PaddleOCR

from app.core.logging import logger

_OCR: PaddleOCR | None = None


def _get_ocr() -> PaddleOCR:
    global _OCR
    if _OCR is None:
        _OCR = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        logger.info("PaddleOCR engine loaded")
    return _OCR


@dataclass
class OcrResult:
    text: str
    confidence: float  # mean confidence across detected text lines, 0.0-1.0


def run_ocr(image_path: str) -> OcrResult:
    """
    Runs OCR on a single extracted keyframe. Confidence below ~0.55 should be
    treated as "insufficient" by the caller, which then escalates to the
    Vision LLM (Section 20.5: OCR first, Vision LLM only when needed).
    """
    ocr = _get_ocr()
    result = ocr.ocr(image_path, cls=True)

    if not result or not result[0]:
        return OcrResult(text="", confidence=0.0)

    lines: list[str] = []
    confidences: list[float] = []
    for line in result[0]:
        _, (text, conf) = line
        lines.append(text)
        confidences.append(conf)

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrResult(text="\n".join(lines), confidence=round(avg_conf, 3))
