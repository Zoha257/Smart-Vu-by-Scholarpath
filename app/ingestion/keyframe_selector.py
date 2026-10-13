"""
app/ingestion/keyframe_selector.py

Keyframe selection (Section 9.2). IMPORTANT: keyframes are an optimization
mechanism for WHICH frames get expensive AI analysis (OCR/Vision LLM) — they
are never a mechanism for removing lecture content. The complete audio
transcript (Section 9.1) always covers 100% of the lecture regardless of
which video frames are selected here.

Architecture: 100% lecture ingestion + selective expensive AI analysis.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from app.core.logging import logger


@dataclass
class Keyframe:
    timestamp: float
    frame_path: str


def select_keyframes(
    video_path: str,
    output_dir: str,
    scene_change_threshold: float = 30.0,
    min_gap_seconds: float = 3.0,
) -> list[Keyframe]:
    """
    Scans the COMPLETE video timeline (Section 9.1) and extracts a frame
    whenever the visual content changes meaningfully (new slide, board
    writeup, diagram) — a simple, dependency-light histogram-difference
    scene-change detector. This keeps OCR/Vision LLM calls proportional to
    how much the screen actually changes, not to video duration.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    keyframes: list[Keyframe] = []
    prev_hist = None
    last_kept_time = -min_gap_seconds
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp = frame_idx / fps
        frame_idx += 1

        # Sample every ~1 second rather than every raw frame — the lecture's
        # AUDIO is still processed in full (Section 9.1); this only controls
        # how often we consider the VIDEO for a new keyframe.
        if frame_idx % max(int(fps), 1) != 0:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
        hist = cv2.normalize(hist, hist).flatten()

        is_scene_change = True
        if prev_hist is not None:
            diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CHISQR)
            is_scene_change = diff > scene_change_threshold

        if is_scene_change and (timestamp - last_kept_time) >= min_gap_seconds:
            frame_path = f"{output_dir}/frame_{timestamp:.2f}.jpg"
            cv2.imwrite(frame_path, frame)
            keyframes.append(Keyframe(timestamp=timestamp, frame_path=frame_path))
            last_kept_time = timestamp

        prev_hist = hist

    cap.release()
    logger.info(f"keyframes_selected video={video_path} count={len(keyframes)}")
    return keyframes
