"""
Downloader task: download videos from source URLs and upload to MinIO.
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from lib.db import get_session
from lib.ytdlp import download_video
from lib.minio_client import upload_file

logger = logging.getLogger(__name__)

VIDEOS_BUCKET = os.environ.get("VRE_VIDEOS_BUCKET", "videos")


@app.task(name="tasks.downloader.download_video", bind=True, max_retries=3)
def download_video_task(self, reel_id: str, source_id: str):
    """
    Download a video from the selected source URL using yt-dlp,
    upload to MinIO videos bucket, record video_files entry,
    and update video status to 'downloaded'.

    Args:
        video_id: The internal video UUID.
        source_id: The video_sources UUID to download from.
    """
    logger.info("Starting download for reel=%s source=%s", reel_id, source_id)
    video_id = reel_id  # alias for compatibility

    # Create job tracking record
    with get_session() as session:
        job_id = str(uuid.uuid4())
        session.execute(
            text("""
                INSERT INTO jobs (id, celery_task_id, job_type, status, started_at, reference_id, reference_type)
                VALUES (:id, :celery_task_id, 'download', 'running', :started_at, :video_id, 'viral_reel')
            """),
            {
                "id": job_id,
                "video_id": video_id,
                "celery_task_id": self.request.id or "unknown",
                "started_at": datetime.now(timezone.utc),
            },
        )

    try:
        # Fetch source URL
        with get_session() as session:
            source = session.execute(
                text("SELECT source_url, source_type FROM video_sources WHERE id = :id"),
                {"id": source_id},
            ).fetchone()

        if not source:
            raise ValueError(f"Source {source_id} not found")

        source_url = source.source_url
        source_type = source.source_type
        logger.info("Downloading from %s (%s)", source_url, source_type)

        # Download with yt-dlp (fast, works for most platforms)
        # Falls back to Playwright (headless browser) if yt-dlp is bot-blocked
        try:
            result = download_video(source_url, video_id)
        except Exception as ytdlp_err:
            logger.warning("yt-dlp failed for %s, trying Playwright browser: %s", video_id, str(ytdlp_err)[:100])
            from lib.playwright_dl import download_via_playwright
            pw_result = download_via_playwright(source_url, video_id)
            if pw_result:
                # Convert Playwright result to match yt-dlp DownloadResult format
                from lib.ytdlp import DownloadResult
                result = DownloadResult(
                    file_path=pw_result["file_path"],
                    info_json_path="",
                    resolution="",
                    fps=0,
                    codec="",
                    bitrate=0,
                    duration=pw_result.get("duration", 0),
                    file_size=pw_result.get("file_size", 0),
                )
            else:
                raise ytdlp_err  # Both failed

        # Upload to MinIO
        minio_key = f"{video_id}/{os.path.basename(result.file_path)}"
        upload_file(result.file_path, VIDEOS_BUCKET, minio_key)

        # Also upload info.json if available
        info_json_key = None
        if result.info_json_path and os.path.exists(result.info_json_path):
            info_json_key = f"{video_id}/{os.path.basename(result.info_json_path)}"
            upload_file(result.info_json_path, VIDEOS_BUCKET, info_json_key)

        # Record video_files entry
        file_id = str(uuid.uuid4())
        with get_session() as session:
            session.execute(
                text("""
                    INSERT INTO video_files (
                        id, viral_reel_id, file_type, minio_bucket, minio_key,
                        resolution, duration_seconds, file_size_bytes,
                        created_at
                    ) VALUES (
                        :id, :video_id, 'raw_download', :minio_bucket, :minio_key,
                        :resolution, :duration_seconds, :file_size_bytes,
                        :created_at
                    )
                """),
                {
                    "id": file_id,
                    "video_id": video_id,
                    "minio_bucket": VIDEOS_BUCKET,
                    "minio_key": minio_key,
                    "resolution": result.resolution or "",
                    "duration_seconds": result.duration,
                    "file_size_bytes": result.file_size,
                    "created_at": datetime.now(timezone.utc),
                },
            )

            # Update video status
            session.execute(
                text("""
                    UPDATE viral_reels
                    SET status = 'downloaded', updated_at = :now
                    WHERE id = :id
                """),
                {"id": video_id, "now": datetime.now(timezone.utc)},
            )

            # Mark source as selected
            session.execute(
                text("""
                    UPDATE video_sources
                    SET is_selected = TRUE
                    WHERE id = :id
                """),
                {"id": source_id},
            )

        # Update job
        with get_session() as session:
            session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'success', finished_at = :now, attempts = attempts + 1
                    WHERE id = :id
                """),
                {"id": job_id, "now": datetime.now(timezone.utc)},
            )

        # Clean up local file
        try:
            os.remove(result.file_path)
            if result.info_json_path and os.path.exists(result.info_json_path):
                os.remove(result.info_json_path)
        except OSError as exc:
            logger.warning("Failed to clean up local files: %s", exc)

        logger.info(
            "Download complete for video=%s: %s, %.1fs, %d bytes",
            video_id, result.resolution, result.duration, result.file_size,
        )

        return {
            "video_id": video_id,
            "file_id": file_id,
            "minio_key": minio_key,
            "resolution": result.resolution,
            "duration": result.duration,
            "file_size": result.file_size,
        }

    except Exception as exc:
        # Before retrying via Celery, try Playwright as last resort
        if "bot" in str(exc).lower() or "Sign in" in str(exc):
            logger.warning("yt-dlp bot-blocked for %s, trying Playwright browser fallback", video_id)
            try:
                from lib.playwright_dl import download_via_playwright
                pw_result = download_via_playwright(source_url, video_id)
                if pw_result and pw_result.get("file_path"):
                    from lib.ytdlp import DownloadResult
                    result = DownloadResult(
                        file_path=pw_result["file_path"],
                        info_json_path="",
                        resolution="",
                        fps=0,
                        codec="",
                        bitrate=0,
                        duration=pw_result.get("duration", 0),
                        file_size=pw_result.get("file_size", os.path.getsize(pw_result["file_path"])),
                    )
                    # Upload to MinIO
                    minio_key = f"{video_id}/{os.path.basename(result.file_path)}"
                    upload_file(result.file_path, VIDEOS_BUCKET, minio_key)

                    file_id = str(uuid.uuid4())
                    with get_session() as session:
                        session.execute(
                            text("""
                                INSERT INTO video_files (id, viral_reel_id, file_type, minio_bucket, minio_key,
                                    resolution, duration_seconds, file_size_bytes, created_at)
                                VALUES (:id, :video_id, 'raw_download', :bucket, :key, :res, :dur, :size, :now)
                            """),
                            {"id": file_id, "video_id": video_id, "bucket": VIDEOS_BUCKET,
                             "key": minio_key, "res": "", "dur": result.duration,
                             "size": result.file_size, "now": datetime.now(timezone.utc)},
                        )
                        session.execute(
                            text("UPDATE viral_reels SET status = 'downloaded', updated_at = :now WHERE id = :id"),
                            {"id": video_id, "now": datetime.now(timezone.utc)},
                        )
                        session.execute(
                            text("UPDATE jobs SET status = 'success', finished_at = :now, attempts = attempts + 1 WHERE id = :id"),
                            {"id": job_id, "now": datetime.now(timezone.utc)},
                        )
                    logger.info("Playwright download SUCCESS for %s (%d bytes)", video_id, result.file_size)
                    return {"video_id": video_id, "file_size": result.file_size, "method": "playwright"}
            except Exception as pw_exc:
                logger.error("Playwright fallback also failed for %s: %s", video_id, pw_exc)

        logger.error("Download failed for video=%s: %s", video_id, exc, exc_info=True)

        with get_session() as session:
            session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'failed', finished_at = :now, attempts = attempts + 1,
                        logs = jsonb_build_object('error', :error)
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "error": str(exc)[:1000],
                },
            )
            session.execute(
                text("""
                    UPDATE viral_reels
                    SET status = 'failed', error_message = :error, updated_at = :now
                    WHERE id = :id
                """),
                {"id": video_id, "now": datetime.now(timezone.utc), "error": str(exc)[:1000]},
            )

        raise self.retry(exc=exc, countdown=180)
