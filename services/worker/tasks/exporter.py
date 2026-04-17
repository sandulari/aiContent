"""Video export task: apply user edits and render final 1080x1920 MP4."""

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from lib.db import get_session
from lib.minio_client import download_file, get_minio_client, upload_file
from lib.video_proc import export_user_video

logger = logging.getLogger(__name__)

VIDEOS_BUCKET = os.environ.get("VRE_VIDEOS_BUCKET", "videos")
EXPORTS_BUCKET = os.environ.get("VRE_EXPORTS_BUCKET", "exports")
WORK_DIR = os.environ.get("VRE_WORK_DIR", "/tmp/vre_processing")


def _parse_jsonb(value):
    """user_exports JSONB columns may return as dict already or as text."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


@app.task(name="tasks.exporter.export_video_task", bind=True, max_retries=2)
def export_video_task(self, export_id: str):
    """Render a user_exports row into a final 1080x1920 MP4 stored in MinIO."""
    logger.info("Starting export for export_id=%s", export_id)

    job_id = str(uuid.uuid4())
    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO jobs (id, celery_task_id, job_type, status,
                    reference_id, reference_type, started_at)
                VALUES (:id, :celery_task_id, 'export', 'running',
                    :ref_id, 'user_export', :started_at)
                """
            ),
            {
                "id": job_id,
                "celery_task_id": self.request.id or "unknown",
                "ref_id": export_id,
                "started_at": datetime.now(timezone.utc),
            },
        )

    local_dir = None
    try:
        with get_session() as session:
            export_row = session.execute(
                text(
                    """
                    SELECT
                        ue.id, ue.viral_reel_id, ue.user_id, ue.template_id,
                        ue.headline_text, ue.subtitle_text, ue.caption_text,
                        ue.headline_style, ue.subtitle_style,
                        ue.video_transform, ue.video_trim, ue.audio_config,
                        ue.logo_overrides, ue.logo_override_key, ue.export_status,
                        ue.export_minio_key
                    FROM user_exports ue
                    WHERE ue.id = :id
                    """
                ),
                {"id": export_id},
            ).fetchone()

        if not export_row:
            raise ValueError(f"Export {export_id} not found")

        reel_id = str(export_row.viral_reel_id)

        with get_session() as session:
            session.execute(
                text("UPDATE user_exports SET export_status = 'exporting' WHERE id = :id"),
                {"id": export_id},
            )

        with get_session() as session:
            video_file = session.execute(
                text(
                    """
                    SELECT id, minio_bucket, minio_key, file_type, resolution, duration_seconds
                    FROM video_files
                    WHERE viral_reel_id = :reel_id
                    ORDER BY
                        CASE file_type
                            WHEN 'enhanced' THEN 1
                            WHEN 'raw_download' THEN 2
                            ELSE 3
                        END,
                        created_at DESC
                    LIMIT 1
                    """
                ),
                {"reel_id": reel_id},
            ).fetchone()

        if not video_file:
            raise ValueError(f"No video file found for viral_reel={reel_id}")

        local_dir = os.path.join(WORK_DIR, f"export_{export_id}")
        os.makedirs(local_dir, exist_ok=True)
        filename = os.path.basename(video_file.minio_key)
        local_video_path = os.path.join(local_dir, filename)

        download_file(video_file.minio_bucket, video_file.minio_key, local_video_path)
        logger.info("Downloaded %s video to %s", video_file.file_type, local_video_path)

        # Resolve the logo source: per-export override takes priority,
        # otherwise fall back to the template's default logo. Brand logos
        # were silently dropped in the original implementation.
        logo_src_path = None
        resolved_logo_key: str | None = None

        if export_row.logo_override_key:
            resolved_logo_key = export_row.logo_override_key
        elif export_row.template_id:
            with get_session() as session:
                tmpl_row = session.execute(
                    text(
                        """
                        SELECT logo_minio_key FROM user_templates
                        WHERE id = :id
                        """
                    ),
                    {"id": str(export_row.template_id)},
                ).fetchone()
            if tmpl_row and tmpl_row.logo_minio_key:
                resolved_logo_key = tmpl_row.logo_minio_key

        if resolved_logo_key:
            key_parts = resolved_logo_key.split("/", 1)
            if len(key_parts) == 2:
                logo_bucket, logo_key = key_parts
            else:
                logo_bucket, logo_key = "logos", resolved_logo_key
            logo_src_path = os.path.join(local_dir, "_logo" + os.path.splitext(logo_key)[1])
            try:
                download_file(logo_bucket, logo_key, logo_src_path)
            except Exception as exc:
                logger.warning("logo download failed: %s", exc)
                logo_src_path = None

        # Custom audio: audio_config.custom_audio_key looks like "audio/<uuid>.mp3".
        audio_config_parsed = _parse_jsonb(export_row.audio_config) or {}
        custom_audio_path = None
        custom_audio_key = audio_config_parsed.get("custom_audio_key") if isinstance(audio_config_parsed, dict) else None
        if custom_audio_key:
            ak_parts = custom_audio_key.split("/", 1)
            if len(ak_parts) == 2:
                audio_bucket, audio_key = ak_parts
            else:
                audio_bucket, audio_key = "audio", custom_audio_key
            ext = os.path.splitext(audio_key)[1] or ".mp3"
            custom_audio_path = os.path.join(local_dir, "_bg_audio" + ext)
            try:
                download_file(audio_bucket, audio_key, custom_audio_path)
            except Exception as exc:
                logger.warning("custom audio download failed: %s", exc)
                custom_audio_path = None

        export_config = {
            "export_id": export_id,
            "video_transform": _parse_jsonb(export_row.video_transform),
            "video_trim": _parse_jsonb(export_row.video_trim),
            "headline_text": export_row.headline_text,
            "headline_style": _parse_jsonb(export_row.headline_style),
            "subtitle_text": export_row.subtitle_text,
            "subtitle_style": _parse_jsonb(export_row.subtitle_style),
            "caption_text": export_row.caption_text,
            "audio_config": audio_config_parsed,
            "logo_overrides": _parse_jsonb(export_row.logo_overrides),
            "template_id": str(export_row.template_id) if export_row.template_id else None,
            "logo_src_path": logo_src_path,
            "custom_audio_path": custom_audio_path,
        }

        output_path = export_user_video(local_video_path, export_config)
        output_size = os.path.getsize(output_path)

        # Atomic re-render: upload to a per-render key first, and only
        # after it's written do we update the DB + delete the previous
        # export object (if any). This way a crashed mid-render never
        # corrupts a previously-successful export.
        render_uuid = str(uuid.uuid4())[:8]
        export_key = f"{export_row.user_id}/{export_id}_final_{render_uuid}.mp4"
        upload_file(output_path, EXPORTS_BUCKET, export_key)
        logger.info("Uploaded export: s3://%s/%s", EXPORTS_BUCKET, export_key)

        # If this export already had a previous render, delete the old
        # object from MinIO so we don't pile up dead files forever.
        previous_key = export_row.export_minio_key or ""
        if previous_key and previous_key != f"{EXPORTS_BUCKET}/{export_key}":
            try:
                parts = previous_key.split("/", 1)
                prev_bucket = parts[0] if len(parts) == 2 else EXPORTS_BUCKET
                prev_obj_key = parts[1] if len(parts) == 2 else previous_key
                get_minio_client().remove_object(prev_bucket, prev_obj_key)
                logger.info("Removed previous export object %s", previous_key)
            except Exception as exc:
                logger.warning("Failed to remove previous export object %s: %s", previous_key, exc)

        export_file_id = str(uuid.uuid4())
        with get_session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO video_files (
                        id, viral_reel_id, user_id, file_type,
                        minio_bucket, minio_key, file_size_bytes,
                        resolution, duration_seconds, created_at
                    ) VALUES (
                        :id, :reel_id, :user_id, 'user_edited',
                        :minio_bucket, :minio_key, :file_size_bytes,
                        '1080x1920', :duration_seconds, :created_at
                    )
                    """
                ),
                {
                    "id": export_file_id,
                    "reel_id": reel_id,
                    "user_id": str(export_row.user_id),
                    "minio_bucket": EXPORTS_BUCKET,
                    "minio_key": export_key,
                    "file_size_bytes": output_size,
                    "duration_seconds": float(video_file.duration_seconds or 0),
                    "created_at": datetime.now(timezone.utc),
                },
            )

            session.execute(
                text(
                    """
                    UPDATE user_exports
                    SET export_status = 'done',
                        export_minio_key = :export_minio_key,
                        exported_at = :now
                    WHERE id = :id
                    """
                ),
                {
                    "id": export_id,
                    "export_minio_key": f"{EXPORTS_BUCKET}/{export_key}",
                    "now": datetime.now(timezone.utc),
                },
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
            "Export complete for export_id=%s: s3://%s/%s (%d bytes)",
            export_id, EXPORTS_BUCKET, export_key, output_size,
        )

        return {
            "export_id": export_id,
            "viral_reel_id": reel_id,
            "minio_key": export_key,
            "file_size": output_size,
            "resolution": "1080x1920",
        }

    except Exception as exc:
        logger.error("Export failed for export_id=%s: %s", export_id, exc, exc_info=True)

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
                text("UPDATE user_exports SET export_status = 'failed' WHERE id = :id"),
                {"id": export_id},
            )

        if local_dir:
            shutil.rmtree(local_dir, ignore_errors=True)

        raise self.retry(exc=exc, countdown=180)
