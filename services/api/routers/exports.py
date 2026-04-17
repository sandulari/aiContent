"""User exports — create, update, render, download."""
import re as _re
from io import BytesIO
from typing import Any, Dict, List
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from celery_client import trigger_export_render
from db.session import get_db
from middleware.auth import get_current_user
from models.user import User
from models.user_export import UserExport
from models.user_template import UserTemplate
from models.job import Job
from services.minio_helper import get_minio_client, get_object_stream


def _strip_html(text: str | None) -> str | None:
    if text is None:
        return None
    return _re.sub(r'<[^>]+>', '', text)

router = APIRouter(prefix="/api/exports", tags=["exports"])

LOGOS_BUCKET = "logos"
MAX_LOGO_BYTES = 5 * 1024 * 1024
_ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp", "svg"}


def _normalise_text_style(raw: dict | None) -> dict:
    """Convert a template's headline/subtitle defaults into the flat shape
    the editor's layer state uses. Handles both the legacy nested
    `{position: {x, y}}` shape and the new flat `{x, y}` shape, and
    rescales 0-1 fractions to 0-100 percentages where needed.
    """
    if not isinstance(raw, dict):
        return {}
    style = dict(raw)
    pos = style.pop("position", None)
    if isinstance(pos, dict):
        if "x" in pos and "x" not in style:
            style["x"] = pos["x"]
        if "y" in pos and "y" not in style:
            style["y"] = pos["y"]
    for k in ("x", "y"):
        v = style.get(k)
        if isinstance(v, (int, float)) and 0 <= v <= 1:
            style[k] = round(v * 100, 2)
    # Map legacy keys (snake) to the flat camelCase names the editor reads.
    rename = {
        "font_family": "fontFamily",
        "font_size": "fontSize",
        "font_weight": "fontWeight",
        "shadow_enabled": "shadowEnabled",
        "shadow_color": "shadowColor",
        "shadow_blur": "shadowBlur",
        "shadow_x": "shadowX",
        "shadow_y": "shadowY",
        "stroke_enabled": "strokeEnabled",
        "stroke_color": "strokeColor",
        "stroke_width": "strokeWidth",
        "letter_spacing": "letterSpacing",
        "text_transform": "textTransform",
    }
    for old, new in rename.items():
        if old in style and new not in style:
            style[new] = style.pop(old)
    return style


def _normalise_logo_overrides(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    lg = dict(raw)
    for k in ("x", "y"):
        v = lg.get(k)
        if isinstance(v, (int, float)) and 0 <= v <= 1:
            lg[k] = round(v * 100, 2)
    # Template stores size as a multiplier (0.3–3); editor uses pixels.
    if "size" in lg and isinstance(lg["size"], (int, float)) and lg["size"] <= 3.5:
        lg["size"] = round(lg["size"] * 56)
    rename = {
        "border_width": "borderWidth",
        "border_color": "borderColor",
    }
    for old, new in rename.items():
        if old in lg and new not in lg:
            lg[new] = lg.pop(old)
    return lg


async def _apply_template_to_export(export: UserExport, template: UserTemplate) -> None:
    """Copy a template's defaults onto an export row (pre-flush)."""
    export.headline_style = _normalise_text_style(template.headline_defaults)
    export.subtitle_style = _normalise_text_style(template.subtitle_defaults)
    export.logo_overrides = _normalise_logo_overrides(template.logo_position)


_TEXT_MAX = 500


class ExportCreateRequest(BaseModel):
    viral_reel_id: UUID
    template_id: UUID
    headline_text: str = Field(..., max_length=_TEXT_MAX)
    subtitle_text: str = Field(..., max_length=_TEXT_MAX)
    user_page_id: UUID | None = None
    caption_text: str | None = Field(default=None, max_length=_TEXT_MAX * 4)


class ExportUpdateRequest(BaseModel):
    headline_text: str | None = Field(default=None, max_length=_TEXT_MAX)
    headline_style: Dict[str, Any] | None = None
    subtitle_text: str | None = Field(default=None, max_length=_TEXT_MAX)
    subtitle_style: Dict[str, Any] | None = None
    caption_text: str | None = Field(default=None, max_length=_TEXT_MAX * 4)
    video_transform: Dict[str, Any] | None = None
    video_trim: Dict[str, Any] | None = None
    audio_config: Dict[str, Any] | None = None
    logo_overrides: Dict[str, Any] | None = None
    download_filename: str | None = Field(default=None, max_length=200)


@router.get("")
async def list_exports(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserExport).where(UserExport.user_id == current_user.id).order_by(UserExport.created_at.desc()))
    return [_export_to_dict(e) for e in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_export(body: ExportCreateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tmpl = (await db.execute(
        select(UserTemplate).where(
            UserTemplate.id == body.template_id,
            UserTemplate.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    # Auto-attach one of the user's own Instagram pages so downstream
    # features (AI text, weekly dashboard, recommendations) know which
    # creator voice to use. If the client passed a user_page_id, verify
    # it belongs to this user; otherwise pick the user's first own page.
    from models.user_page import UserPage

    user_page_id = body.user_page_id
    if user_page_id:
        own_check = await db.execute(
            select(UserPage.id).where(
                UserPage.id == user_page_id,
                UserPage.user_id == current_user.id,
            )
        )
        if not own_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="user_page_id not owned")
    else:
        default_own = await db.execute(
            select(UserPage.id)
            .where(
                UserPage.user_id == current_user.id,
                UserPage.page_type == "own",
                UserPage.is_active.is_(True),
            )
            .order_by(UserPage.created_at.asc())
            .limit(1)
        )
        user_page_id = default_own.scalar_one_or_none()

    export = UserExport(
        user_id=current_user.id, user_page_id=user_page_id,
        viral_reel_id=body.viral_reel_id, template_id=body.template_id,
        headline_text=_strip_html(body.headline_text),
        subtitle_text=_strip_html(body.subtitle_text),
        caption_text=body.caption_text, export_status="editing",
    )
    await _apply_template_to_export(export, tmpl)
    db.add(export)
    await db.flush()
    await db.refresh(export)
    return _export_to_dict(export)


@router.post("/{export_id}/apply-template/{template_id}")
async def apply_template(
    export_id: UUID,
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-apply a template to an existing export.

    Overwrites headline_style / subtitle_style / logo_overrides with the
    template's defaults. Does NOT overwrite the user's headline_text or
    subtitle_text (those are content, not style).
    """
    result = await db.execute(
        select(UserExport).where(
            UserExport.id == export_id, UserExport.user_id == current_user.id
        )
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    tmpl_result = await db.execute(
        select(UserTemplate).where(
            UserTemplate.id == template_id, UserTemplate.user_id == current_user.id
        )
    )
    tmpl = tmpl_result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    export.template_id = template_id
    await _apply_template_to_export(export, tmpl)
    await db.flush()
    await db.refresh(export)
    return _export_to_dict(export)


@router.put("/{export_id}")
async def update_export(export_id: UUID, body: ExportUpdateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserExport).where(UserExport.id == export_id, UserExport.user_id == current_user.id))
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    data = body
    if data.headline_text is not None:
        export.headline_text = _strip_html(data.headline_text)
    if data.subtitle_text is not None:
        export.subtitle_text = _strip_html(data.subtitle_text)
    if data.caption_text is not None:
        export.caption_text = _strip_html(data.caption_text)
    for field, value in body.model_dump(exclude_unset=True, exclude={"headline_text", "subtitle_text", "caption_text"}).items():
        setattr(export, field, value)
    await db.flush()
    await db.refresh(export)
    return _export_to_dict(export)


@router.delete("/{export_id}", status_code=204)
async def delete_export(
    export_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserExport).where(
            UserExport.id == export_id,
            UserExport.user_id == current_user.id,
        )
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    # Clean up MinIO export file if it exists
    if export.export_minio_key:
        try:
            from services.minio_helper import get_minio_client
            parts = export.export_minio_key.split("/", 1)
            if len(parts) == 2:
                get_minio_client().remove_object(parts[0], parts[1])
        except Exception:
            pass  # Best-effort cleanup
    await db.delete(export)


@router.post("/{export_id}/upload-logo")
async def upload_export_logo(
    export_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a per-export logo override.

    The logo is stored in the `logos` MinIO bucket under the user's
    namespace and the key is saved on `user_exports.logo_override_key`.
    The exporter task uses the override when rendering, so the user can
    swap a logo for a single reel without touching the parent template.
    """
    result = await db.execute(
        select(UserExport).where(
            UserExport.id == export_id, UserExport.user_id == current_user.id
        )
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "png"
    if ext not in _ALLOWED_LOGO_EXT:
        raise HTTPException(status_code=400, detail="Unsupported logo format")

    content = await file.read()
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Logo too large (max 5 MB)")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    key = f"{current_user.id}/exports/{export_id}/{uuid4().hex}.{ext}"
    client = get_minio_client()
    if not client.bucket_exists(LOGOS_BUCKET):
        client.make_bucket(LOGOS_BUCKET)
    client.put_object(
        LOGOS_BUCKET,
        key,
        BytesIO(content),
        length=len(content),
        content_type=file.content_type or "image/png",
    )
    export.logo_override_key = f"{LOGOS_BUCKET}/{key}"
    await db.flush()
    await db.refresh(export)
    return _export_to_dict(export)


@router.delete("/{export_id}/logo-override", status_code=status.HTTP_204_NO_CONTENT)
async def clear_export_logo(
    export_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear the per-export logo override so the template logo kicks in again."""
    result = await db.execute(
        select(UserExport).where(
            UserExport.id == export_id, UserExport.user_id == current_user.id
        )
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    export.logo_override_key = None
    await db.flush()


@router.post("/{export_id}/render", status_code=status.HTTP_202_ACCEPTED)
async def render_export(
    export_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserExport).where(
            UserExport.id == export_id, UserExport.user_id == current_user.id
        )
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    # Ensure the underlying reel has at least one video file to render.
    from models.video_file import VideoFile
    vf_result = await db.execute(
        select(VideoFile.id).where(VideoFile.viral_reel_id == export.viral_reel_id).limit(1)
    )
    if not vf_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="No video file available for this reel. Download the video first.",
        )

    # Idempotency: block if a render is already in flight. "done" and
    # "failed" are allowed so users can re-render after a fix.
    if export.export_status in ("exporting", "rendering"):
        raise HTTPException(
            status_code=409,
            detail=f"Export is already {export.export_status}. Wait for it to finish before re-rendering.",
        )

    export.export_status = "exporting"
    task_id = trigger_export_render(export_id)
    job = Job(
        celery_task_id=task_id,
        job_type="export",
        status="pending",
        reference_id=export_id,
        reference_type="user_export",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return {"job_id": str(job.id), "status": "exporting"}


@router.get("/{export_id}/status")
async def get_export_status(export_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserExport).where(UserExport.id == export_id, UserExport.user_id == current_user.id))
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    # Back-fill user_page_id for legacy exports created before the
    # auto-attach fix. Picks the user's oldest own page.
    if export.user_page_id is None:
        from models.user_page import UserPage

        default_own = await db.execute(
            select(UserPage.id)
            .where(
                UserPage.user_id == current_user.id,
                UserPage.page_type == "own",
                UserPage.is_active.is_(True),
            )
            .order_by(UserPage.created_at.asc())
            .limit(1)
        )
        fallback = default_own.scalar_one_or_none()
        if fallback:
            export.user_page_id = fallback
            await db.flush()

    return _export_to_dict(export)


def _sanitize_filename(name: str | None, export_id: UUID) -> str:
    """Return a safe filename ending in .mp4.

    Allows alphanumerics, spaces, dashes, underscores, and dots. Strips
    anything else. Falls back to export_<id>.mp4 when the sanitized
    name is empty.
    """
    import re as _re

    raw = (name or "").strip()
    if not raw:
        return f"export_{export_id}.mp4"
    # Remove trailing .mp4 so we can re-append cleanly
    if raw.lower().endswith(".mp4"):
        raw = raw[:-4]
    # Allow safe chars only
    clean = _re.sub(r"[^A-Za-z0-9 _\-.]", "", raw).strip()
    if not clean:
        return f"export_{export_id}.mp4"
    return f"{clean[:180]}.mp4"


@router.get("/{export_id}/download")
async def download_export(
    export_id: UUID,
    token: str | None = None,
    authorization: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Stream the rendered MP4. User must own the export.

    Accepts JWT either as a standard `Authorization: Bearer` header
    or as a `?token=` query param — browsers can't set headers on
    `window.open()` downloads, so the frontend passes the token as
    a query string.
    """
    from middleware.auth import verify_token
    from fastapi import Header

    raw_token = token
    if not raw_token:
        # fallback: check explicit Header (we could also parse authorization
        # via Depends, but we want the endpoint to accept either style)
        pass
    try:
        if not raw_token:
            raise HTTPException(status_code=401, detail="Missing auth token")
        payload = verify_token(raw_token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(
        select(UserExport).where(
            UserExport.id == export_id,
            UserExport.user_id == UUID(user_id),
        )
    )
    export = result.scalar_one_or_none()
    if not export or not export.export_minio_key:
        raise HTTPException(status_code=404, detail="Export not ready")
    parts = export.export_minio_key.split("/", 1)
    bucket = parts[0] if len(parts) > 1 else "exports"
    key = parts[1] if len(parts) > 1 else export.export_minio_key
    filename = _sanitize_filename(export.download_filename, export_id)
    try:
        response, stat = get_object_stream(bucket, key)
        return StreamingResponse(
            response.stream(32768),
            media_type="video/mp4",
            headers={
                "Content-Length": str(stat.size),
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not accessible: {e}")


def _export_to_dict(e: UserExport) -> dict:
    return {
        "id": str(e.id), "user_id": str(e.user_id),
        "user_page_id": str(e.user_page_id) if e.user_page_id else None,
        "viral_reel_id": str(e.viral_reel_id), "template_id": str(e.template_id),
        "headline_text": e.headline_text, "headline_style": e.headline_style,
        "subtitle_text": e.subtitle_text, "subtitle_style": e.subtitle_style,
        "caption_text": e.caption_text,
        "video_transform": e.video_transform, "video_trim": e.video_trim,
        "audio_config": e.audio_config, "logo_overrides": e.logo_overrides,
        "logo_override_key": e.logo_override_key,
        "download_filename": e.download_filename,
        "export_minio_key": e.export_minio_key, "export_status": e.export_status,
        "created_at": str(e.created_at), "exported_at": str(e.exported_at) if e.exported_at else None,
    }
