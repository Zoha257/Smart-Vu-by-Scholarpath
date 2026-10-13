"""
app/storage/r2_client.py

Cloudflare R2 client (Section 14.3, 18.2) — S3-compatible, so boto3 works
unmodified. The Admin App WRITES here during ingestion (keyframes, generated
PDFs, enhanced images); the Client App only READS to serve assets.

R2's zero-egress-fee model is why this was chosen over Oracle's own object
storage or Supabase Storage (Section 14.3 rationale) — it matters because the
Client App is public and free for every visitor.
"""
import mimetypes
import uuid

import boto3
from botocore.config import Config

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()

_s3 = boto3.client(
    "s3",
    endpoint_url=settings.R2_ENDPOINT_URL,
    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="auto",
)


def upload_file(local_path: str, key_prefix: str = "assets") -> str:
    """
    Uploads a local file to R2 under a random key, returns the PUBLIC url
    (via R2_PUBLIC_BASE_URL if configured, else a presigned URL as fallback).
    Used for keyframes, enhanced images, and generated notes PDFs.
    """
    ext = local_path.rsplit(".", 1)[-1] if "." in local_path else "bin"
    key = f"{key_prefix}/{uuid.uuid4().hex}.{ext}"
    content_type, _ = mimetypes.guess_type(local_path)

    _s3.upload_file(
        local_path,
        settings.R2_BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type or "application/octet-stream"},
    )
    logger.info(f"r2_upload key={key}")

    if settings.R2_PUBLIC_BASE_URL:
        return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"

    # Fallback: 7-day presigned URL if no public domain is configured yet.
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
        ExpiresIn=60 * 60 * 24 * 7,
    )


def delete_object(key: str) -> None:
    _s3.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    logger.info(f"r2_delete key={key}")
