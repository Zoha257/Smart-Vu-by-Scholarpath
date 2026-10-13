"""
app/ai_clients/esrgan_pipeline.py

Real-ESRGAN wrapper (Section 8.7). OPTIONAL visual enhancement — improves
readability of low-quality keyframes, does NOT recreate missing information
(Section 20.3: "upscaling cannot reliably recover information that does not
exist in the source"). Only invoked for keyframes flagged low-quality by the
ingestion pipeline (Section 7.5), not for every frame.
"""
import cv2
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet

from app.core.logging import logger

_UPSCALER: RealESRGANer | None = None


def _get_upscaler() -> RealESRGANer:
    global _UPSCALER
    if _UPSCALER is None:
        model = RRDBNet(
            num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2
        )
        _UPSCALER = RealESRGANer(
            scale=2,
            model_path="weights/RealESRGAN_x2plus.pth",  # download separately, see README
            model=model,
            tile=256,          # keeps memory bounded on a free-tier VM
            half=False,        # CPU-safe; set True only with a CUDA GPU
        )
        logger.info("Real-ESRGAN upscaler loaded (x2, tile=256)")
    return _UPSCALER


def enhance_image(input_path: str, output_path: str) -> str:
    """
    Upscales/sharpens a single low-quality keyframe. The caller (ingestion
    pipeline) is responsible for deciding WHICH frames qualify — this
    function does not judge quality itself.
    """
    upscaler = _get_upscaler()
    img = cv2.imread(input_path, cv2.IMREAD_COLOR)
    output, _ = upscaler.enhance(img, outscale=2)
    cv2.imwrite(output_path, output)
    logger.info(f"image_enhanced input={input_path} output={output_path}")
    return output_path
