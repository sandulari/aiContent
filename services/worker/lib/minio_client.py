"""
MinIO object storage helpers for uploading and downloading files.
"""

import os
import logging
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

_client = None


def get_minio_client() -> Minio:
    """Return a singleton MinIO client instance."""
    global _client
    if _client is None:
        endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
        access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
        secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
        _client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        logger.info("MinIO client initialized (endpoint=%s)", endpoint)
    return _client


def _ensure_bucket(client: Minio, bucket: str):
    """Create bucket if it does not exist."""
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("Created bucket: %s", bucket)
    except S3Error as exc:
        logger.error("Failed to ensure bucket %s: %s", bucket, exc)
        raise


def upload_file(local_path: str, bucket: str, key: str) -> str:
    """
    Upload a local file to MinIO.

    Returns the object key on success.
    """
    client = get_minio_client()
    _ensure_bucket(client, bucket)

    file_size = os.path.getsize(local_path)
    logger.info("Uploading %s → s3://%s/%s (%d bytes)", local_path, bucket, key, file_size)

    client.fput_object(bucket, key, local_path)
    logger.info("Upload complete: s3://%s/%s", bucket, key)
    return key


def download_file(bucket: str, key: str, local_path: str) -> str:
    """
    Download a file from MinIO to a local path.

    Returns the local file path on success.
    """
    client = get_minio_client()
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    logger.info("Downloading s3://%s/%s → %s", bucket, key, local_path)
    client.fget_object(bucket, key, local_path)
    logger.info("Download complete: %s", local_path)
    return local_path
