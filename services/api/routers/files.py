import os
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.user import User
from models.video_file import VideoFile
from services.minio_helper import get_minio_client, get_object_stream

MAX_AUDIO_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB cap

router = APIRouter(prefix="/api/files", tags=["files"])

MINIO_AUDIO_BUCKET = os.getenv("MINIO_BUCKET_AUDIO", "audio")


@router.get("/{file_id}/download")
async def download_file(file_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stream a file from MinIO through the API (no presigned URL needed)."""
    vf = await db.get(VideoFile, file_id)
    if not vf:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        response, stat = get_object_stream(vf.minio_bucket, vf.minio_key)
        content_type = "video/mp4" if vf.minio_key.endswith(".mp4") else "application/octet-stream"
        return StreamingResponse(
            response.stream(32 * 1024),
            media_type=content_type,
            headers={
                "Content-Length": str(stat.size),
                "Content-Disposition": f'attachment; filename="{os.path.basename(vf.minio_key)}"',
            },
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not accessible: {e}")


@router.get("/video/{video_id}/stream")
async def stream_video(video_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stream the source video file for editor preview.

    CRITICAL: must never return a `user_edited` file (those have the
    user's text/logo baked in via the exporter). The editor needs the
    clean source so users can keep editing on top of it after rendering.
    Preference order: enhanced > raw_download > anything else that
    isn't a user edit. Only falls back to a user edit as a last resort.
    """
    # Pull every file for this reel and pick the best source.
    result = await db.execute(
        select(VideoFile)
        .where(VideoFile.viral_reel_id == video_id)
        .order_by(VideoFile.created_at.desc())
    )
    files = result.scalars().all()
    if not files:
        raise HTTPException(status_code=404, detail="No video file found")

    def _rank(ft: str | None) -> int:
        # Lower is better.
        return {
            "enhanced": 0,
            "raw_download": 1,
            "source": 2,
            "user_edited": 99,
        }.get((ft or "").lower(), 50)

    files.sort(key=lambda f: (_rank(f.file_type), -int(f.created_at.timestamp() if f.created_at else 0)))
    vf = files[0]

    try:
        response, stat = get_object_stream(vf.minio_bucket, vf.minio_key)
        return StreamingResponse(
            response.stream(32 * 1024),
            media_type="video/mp4",
            headers={
                "Content-Length": str(stat.size),
                "Accept-Ranges": "bytes",
                "X-Video-Resolution": vf.resolution or "",
                "X-Video-Duration": str(vf.duration_seconds or 0),
                "X-Video-File-Type": vf.file_type or "",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Video not accessible: {e}")


@router.get("/export-logo/{export_id}")
async def serve_export_logo(export_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Serve the per-export logo override (if set) or fall back to the
    template's logo. Lets the editor show the right image whether the
    user uploaded a custom logo just for this reel or is using the
    template default."""
    from models.user_export import UserExport
    from models.user_template import UserTemplate

    exp_res = await db.execute(select(UserExport).where(UserExport.id == export_id))
    exp = exp_res.scalar_one_or_none()
    if not exp:
        raise HTTPException(status_code=404, detail="Export not found")

    key = exp.logo_override_key
    if not key and exp.template_id:
        tmpl_res = await db.execute(
            select(UserTemplate).where(UserTemplate.id == exp.template_id)
        )
        tmpl = tmpl_res.scalar_one_or_none()
        if tmpl:
            key = tmpl.logo_minio_key
    if not key:
        raise HTTPException(status_code=404, detail="No logo")

    parts = key.split("/", 1)
    bucket = parts[0] if len(parts) > 1 else "logos"
    minio_key = parts[1] if len(parts) > 1 else key
    try:
        response, stat = get_object_stream(bucket, minio_key)
        ext = minio_key.rsplit(".", 1)[-1].lower() if "." in minio_key else "png"
        ct = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "svg": "image/svg+xml",
            "webp": "image/webp",
        }.get(ext, "image/png")
        return StreamingResponse(
            response.stream(8192),
            media_type=ct,
            headers={
                "Cache-Control": "public, max-age=300",
                "Cross-Origin-Resource-Policy": "cross-origin",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Logo not accessible: {e}")


@router.get("/logo/{template_id}")
async def serve_logo(template_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Serve the logo image for a template."""
    from models.user_template import UserTemplate
    result = await db.execute(select(UserTemplate).where(UserTemplate.id == template_id))
    tmpl = result.scalar_one_or_none()
    if not tmpl or not tmpl.logo_minio_key:
        raise HTTPException(status_code=404, detail="Logo not found")
    # logo_minio_key is like "logos/user_id/template_id/hash.png"
    parts = tmpl.logo_minio_key.split("/", 1)
    bucket = parts[0] if len(parts) > 1 else "logos"
    key = parts[1] if len(parts) > 1 else tmpl.logo_minio_key
    try:
        response, stat = get_object_stream(bucket, key)
        ext = key.rsplit(".", 1)[-1].lower() if "." in key else "png"
        ct = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(ext, "image/png")
        return StreamingResponse(response.stream(8192), media_type=ct, headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Logo not accessible: {e}")


# 1×1 transparent PNG — served when the upstream IG CDN thumbnail is gone
# (URLs expire within hours). Lets the <img> tag render cleanly without
# triggering Chrome's ORB blocking on a 404 JSON response.
_PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x18\x15\xeb8\x00\x00\x00\x00IEND\xaeB`\x82"
)

_IMG_PROXY_HEADERS = {
    "Cache-Control": "public, max-age=3600",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "X-Content-Type-Options": "nosniff",
}


def _placeholder_response():
    return StreamingResponse(
        iter([_PLACEHOLDER_PNG]),
        media_type="image/png",
        headers=_IMG_PROXY_HEADERS,
    )


@router.get("/thumbnail/{reel_id}")
async def proxy_thumbnail(reel_id: UUID, db: AsyncSession = Depends(get_db)):
    """Proxy Instagram thumbnail through our server.

    Instagram CDN URLs expire within hours. Rather than 404 on expiry
    (which Chrome flags as ORB-blocked because an <img> sees a JSON
    response), we return a 1×1 transparent PNG so the frontend renders
    cleanly and cards fall through to their text content.
    """
    from models.viral_reel import ViralReel

    result = await db.execute(select(ViralReel).where(ViralReel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel:
        return _placeholder_response()

    # Use Instagram's public media endpoint (never expires, no API key needed)
    # Falls back to stored CDN URL if shortcode extraction fails
    code = reel.ig_video_id
    thumb_url = f"https://www.instagram.com/p/{code}/media/?size=m" if code else reel.thumbnail_url
    if not thumb_url:
        return _placeholder_response()

    import httpx

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                thumb_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Referer": "https://www.instagram.com/",
                },
            )
    except httpx.RequestError:
        return _placeholder_response()

    if resp.status_code != 200:
        return _placeholder_response()

    ct = resp.headers.get("content-type", "image/jpeg")
    if not ct.startswith("image/"):
        ct = "image/jpeg"
    return StreamingResponse(
        iter([resp.content]),
        media_type=ct,
        headers=_IMG_PROXY_HEADERS,
    )


@router.get("/video/{video_id}/info")
async def video_info(video_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Metadata for the editor's source video.

    Same source-preference order as /video/{id}/stream so duration,
    resolution, and codec the editor shows always match the file it's
    playing. Never returns metadata from a user_edited export.
    """
    result = await db.execute(
        select(VideoFile)
        .where(VideoFile.viral_reel_id == video_id)
        .order_by(VideoFile.created_at.desc())
    )
    files = result.scalars().all()
    if not files:
        raise HTTPException(status_code=404, detail="No video file found")

    def _rank(ft: str | None) -> int:
        return {
            "enhanced": 0,
            "raw_download": 1,
            "source": 2,
            "user_edited": 99,
        }.get((ft or "").lower(), 50)

    files.sort(key=lambda f: (_rank(f.file_type), -int(f.created_at.timestamp() if f.created_at else 0)))
    vf = files[0]
    return JSONResponse({
        "url": f"/api/files/video/{video_id}/stream",
        "resolution": vf.resolution,
        "duration_seconds": vf.duration_seconds,
        "file_size_bytes": vf.file_size_bytes,
        "file_type": vf.file_type,
    })


_ALLOWED_AUDIO_EXT = {"mp3", "wav", "m4a", "aac", "ogg"}


@router.post("/upload-audio")
async def upload_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a background audio track. Authenticated + size-capped."""
    ext_raw = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "mp3"
    if ext_raw not in _ALLOWED_AUDIO_EXT:
        raise HTTPException(status_code=400, detail="Unsupported audio format")

    content = await file.read()
    if len(content) > MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large (max 25 MB)")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    object_name = f"{current_user.id}/{uuid4().hex}.{ext_raw}"

    client = get_minio_client()
    if not client.bucket_exists(MINIO_AUDIO_BUCKET):
        client.make_bucket(MINIO_AUDIO_BUCKET)

    client.put_object(
        MINIO_AUDIO_BUCKET,
        object_name,
        BytesIO(content),
        length=len(content),
        content_type=file.content_type or "audio/mpeg",
    )
    return JSONResponse(
        {
            "minio_key": f"{MINIO_AUDIO_BUCKET}/{object_name}",
            "bucket": MINIO_AUDIO_BUCKET,
            "key": object_name,
            "size_bytes": len(content),
        },
        status_code=201,
    )
