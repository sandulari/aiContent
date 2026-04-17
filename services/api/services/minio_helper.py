"""Shared MinIO client helpers for all routers."""
import os
from datetime import timedelta
from io import BytesIO
from minio import Minio

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"


def get_minio_client() -> Minio:
    """Internal client for all MinIO operations."""
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)


def get_object_stream(bucket: str, key: str):
    """Get a file stream from MinIO. Returns (data_stream, stat)."""
    client = get_minio_client()
    response = client.get_object(bucket, key)
    stat = client.stat_object(bucket, key)
    return response, stat
