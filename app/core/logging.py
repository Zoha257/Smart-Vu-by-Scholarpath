"""
app/core/logging.py

Structured logging so we can later satisfy Section 8.2's requirement to log
which application / model / feature served each generation (for shared Groq
budget monitoring — Section 20.7).
"""
import sys

from loguru import logger

from app.core.config import get_settings

settings = get_settings()

logger.remove()
logger.add(
    sys.stdout,
    level=settings.LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | "
           "<cyan>{extra[app]}</cyan> | {message}",
)
logger = logger.bind(app="admin")

__all__ = ["logger"]
