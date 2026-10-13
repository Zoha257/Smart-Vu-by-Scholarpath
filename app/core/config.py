"""
app/core/config.py

Central configuration for the Admin App, loaded from environment variables
(.env). Mirrors SRS Section 19.2 (shared infra) and Section 8.2 (model routing).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database (Section 14.1) ---
    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    # --- Groq (Section 8.2, 18.4) ---
    GROQ_API_KEY: str
    GROQ_MODEL_DEFAULT: str = "llama-3.1-8b-instant"
    GROQ_MODEL_ESCALATION: str = "llama-3.3-70b-versatile"
    GROQ_VISION_MODEL: str = "llama-3.2-11b-vision-preview"

    # --- Cloudflare R2 (Section 14.3) ---
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    R2_ENDPOINT_URL: str
    R2_PUBLIC_BASE_URL: str = ""

    # --- Admin access control (Section 17.2) ---
    ADMIN_API_KEY: str

    # --- Embeddings (Section 8.5) ---
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384

    # --- Network binding (Section 18.5) ---
    ADMIN_APP_HOST: str = "127.0.0.1"
    ADMIN_APP_PORT: int = 8001

    # --- Ingestion pacing (Section 22.7) ---
    MAX_LECTURES_INGESTED_PER_DAY: int = 8

    # --- Local file upload (alternative to URL fetch, Section 21.3) ---
    # Holds an uploaded lecture video ONLY until the pipeline consumes it;
    # the pipeline deletes it the same way it deletes a yt-dlp-fetched file.
    LOCAL_UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 2048  # 2GB — plenty for a 55-min 720p lecture

    # --- Optional ---
    YT_DLP_COOKIES_FILE: str = ""
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — read env once per process."""
    return Settings()
