"""Video enhancement task: pull raw from MinIO, run enhancement pipeline,
upload result, update DB.
"""

import logging
import os
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from lib.db import get_session
from lib.minio_client import download_file, upload_file
from lib.video_proc import enhance_video, get_video_resolution, get_video_fps

logger = logging.getLogger(__name__)

VIDEOS_BUCKET = os.environ.get("VRE_VIDEOS_BUCKET", "videos")
WORK_DIR = os.environ.get("VRE_WORK_DIR", "/tmp/vre_processing")


@app.task(name="tasks.enhancer.enhance_video_task", bind=True, max_retries=2)
def enhance_video_task(self, reel_id: str):
    """Enhance a downloaded viral reel.

    Args:
        reel_id: UUID of the viral_reels row to enhance.
    """
    logger.info("Starting enhancement for viral_reel=%s", reel_id)

    job_id = str(uuid.uuid4())
    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO jobs (id, celery_task_id, job_type, status,
                    reference_id, reference_type, started_at)
                VALUES (:id, :celery_task_id, 'enhance', 'running',
                    :ref_id, 'viral_reel', :started_at)
                """
            ),
            {
                "id": job_id,
                "celery_task_id": self.request.id or "unknown",
                "ref_id": reel_id,
                "started_at": datetime.now(timezone.utc),
            },
        )

    local_dir = None
    try:
        with get_session() as session:
            raw_file = session.execute(
                text(
                    """
                    SELECT id, minio_bucket, minio_key, resolution
                    FROM video_files
                    WHERE viral_reel_id = :reel_id AND file_type = 'raw_download'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"reel_id": reel_id},
            ).fetchone()

        if not raw_file:
            raise ValueError(f"No raw video file found for viral_reel={reel_id}")

        local_dir = os.path.join(WORK_DIR, f"enhance_{reel_id}")
        os.makedirs(local_dir, exist_ok=True)
        filename = os.path.basename(raw_file.minio_key)
        local_path = os.path.join(local_dir, filename)

        download_file(raw_file.minio_bucket, raw_file.minio_key, local_path)
        logger.info("Downloaded raw video to %s", local_path)

        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE viral_reels SET status = 'enhancing', updated_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": reel_id, "now": datetime.now(timezone.utc)},
            )

        enhanced_path = enhance_video(local_path, reel_id)
        enhanced_resolution = get_video_resolution(enhanced_path) or ""
        enhanced_fps = get_video_fps(enhanced_path) or 0.0
        enhanced_size = os.path.getsize(enhanced_path)

        enhanced_key = f"{reel_id}/{reel_id}_enhanced.mp4"
        upload_file(enhanced_path, VIDEOS_BUCKET, enhanced_key)
        logger.info("Uploaded enhanced video: s3://%s/%s", VIDEOS_BUCKET, enhanced_key)

        enhanced_file_id = str(uuid.uuid4())
        with get_session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO video_files (
                        id, viral_reel_id, file_type, minio_bucket, minio_key,
                        resolution, duration_seconds, file_size_bytes, created_at
                    ) VALUES (
                        :id, :reel_id, 'enhanced', :minio_bucket, :minio_key,
                        :resolution, :duration_seconds, :file_size_bytes, :created_at
                    )
                    """
                ),
                {
                    "id": enhanced_file_id,
                    "reel_id": reel_id,
                    "minio_bucket": VIDEOS_BUCKET,
                    "minio_key": enhanced_key,
                    "resolution": enhanced_resolution,
                    "duration_seconds": 0.0,
                    "file_size_bytes": enhanced_size,
                    "created_at": datetime.now(timezone.utc),
                },
            )

            session.execute(
                text(
                    """
                    UPDATE viral_reels SET status = 'enhanced', updated_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": reel_id, "now": datetime.now(timezone.utc)},
            )

            session.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = 'success', finished_at = :now, attempts = attempts + 1
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "now": datetime.now(timezone.utc)},
            )

        if local_dir:
            shutil.rmtree(local_dir, ignore_errors=True)

        logger.info(
            "Enhancement complete for viral_reel=%s: %s @ %.1f fps, %d bytes",
            reel_id, enhanced_resolution, enhanced_fps, enhanced_size,
        )

        return {
            "viral_reel_id": reel_id,
            "enhanced_file_id": enhanced_file_id,
            "minio_key": enhanced_key,
            "resolution": enhanced_resolution,
            "fps": enhanced_fps,
            "file_size": enhanced_size,
        }

    except Exception as exc:
        logger.error("Enhancement failed for viral_reel=%s: %s", reel_id, exc, exc_info=True)

        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = 'failed', finished_at = :now, attempts = attempts + 1,
                        logs = jsonb_build_object('error', :error)
                    WHERE id = :id
                    """
                ),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "error": str(exc)[:1000],
                },
            )
            session.execute(
                text(
                    """
                    UPDATE viral_reels
                    SET status = 'failed', error_message = :error, updated_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": reel_id, "now": datetime.now(timezone.utc), "error": str(exc)[:1000]},
            )

        if local_dir:
            shutil.rmtree(local_dir, ignore_errors=True)

        raise self.retry(exc=exc, countdown=300)
