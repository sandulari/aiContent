"""User templates — CRUD + logo upload."""
from io import BytesIO
from typing import Any, Dict, List
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from middleware.auth import get_current_user
from models.user import User
from models.user_export import UserExport
from models.user_template import UserTemplate
from services.minio_helper import get_minio_client

MAX_LOGO_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp", "svg"}

router = APIRouter(prefix="/api/templates", tags=["templates"])
LOGOS_BUCKET = "logos"


# Flat defaults that match the editor's layer prop shape, so when the
# template is copied into an export it flows straight into Canvas +
# PropertiesPanel with no transformation.
DEFAULT_LOGO = {
    "x": 50, "y": 8,
    "size": 56,
    "opacity": 100,
    "borderWidth": 2,
    "borderColor": "#484f58",
}

DEFAULT_HEADLINE = {
    "fontFamily": "Inter",
    "fontSize": 48,
    "fontWeight": 700,
    "color": "#FFFFFF",
    "alignment": "center",
    "letterSpacing": 0,
    "textTransform": "none",
    "shadowEnabled": True,
    "shadowColor": "#000000",
    "shadowBlur": 6,
    "shadowX": 0,
    "shadowY": 2,
    "strokeEnabled": False,
    "strokeColor": "#000000",
    "strokeWidth": 2,
    "opacity": 100,
    "x": 50,
    "y": 68,
}

DEFAULT_SUBTITLE = {
    "fontFamily": "Inter",
    "fontSize": 22,
    "fontWeight": 400,
    "color": "#C9D1D9",
    "alignment": "center",
    "letterSpacing": 0,
    "textTransform": "none",
    "shadowEnabled": True,
    "shadowColor": "#000000",
    "shadowBlur": 4,
    "shadowX": 0,
    "shadowY": 1,
    "strokeEnabled": False,
    "strokeColor": "#000000",
    "strokeWidth": 1,
    "opacity": 100,
    "x": 50,
    "y": 80,
}


from pydantic import Field


class TemplateCreateRequest(BaseModel):
    template_name: str = Field(..., min_length=1, max_length=100)
    user_page_id: str | None = None
    logo_position: Dict[str, Any] | None = None
    headline_defaults: Dict[str, Any] | None = None
    subtitle_defaults: Dict[str, Any] | None = None
    # Optional: multi-layer text definitions. When provided, overrides
    # the default of a headline+subtitle pair. See video_proc.py for
    # per-layer schema.
    text_layers: List[Dict[str, Any]] | None = None
    background_color: str = Field(default="#000000", max_length=20)


class TemplateUpdateRequest(BaseModel):
    template_name: str | None = Field(default=None, min_length=1, max_length=100)
    logo_position: Dict[str, Any] | None = None
    headline_defaults: Dict[str, Any] | None = None
    subtitle_defaults: Dict[str, Any] | None = None
    text_layers: List[Dict[str, Any]] | None = None
    background_color: str | None = Field(default=None, max_length=20)
    is_default: bool | None = None


@router.get("")
async def list_templates(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserTemplate).where(UserTemplate.user_id == current_user.id).order_by(UserTemplate.created_at.desc()))
    return [_tpl_dict(t) for t in result.scalars().all()]


@router.get("/{template_id}")
async def get_template(template_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserTemplate).where(UserTemplate.id == template_id, UserTemplate.user_id == current_user.id))
    t = result.scalar_one_or_none()
    if not t: raise HTTPException(status_code=404, detail="Template not found")
    return _tpl_dict(t)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(body: TemplateCreateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # If this is the user's first template, make it default.
    count = (await db.execute(
        select(UserTemplate).where(UserTemplate.user_id == current_user.id)
    )).scalars().first()
    is_first = count is None

    t = UserTemplate(
        user_id=current_user.id,
        template_name=body.template_name,
        logo_position=body.logo_position or DEFAULT_LOGO,
        headline_defaults=body.headline_defaults or DEFAULT_HEADLINE,
        subtitle_defaults=body.subtitle_defaults or DEFAULT_SUBTITLE,
        text_layers=body.text_layers if body.text_layers is not None else [],
        background_color=body.background_color,
        is_default=is_first,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return _tpl_dict(t)


@router.post("/{template_id}/set-default")
async def set_default(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a template as the user's default; clears the flag on others."""
    result = await db.execute(
        select(UserTemplate).where(
            UserTemplate.id == template_id, UserTemplate.user_id == current_user.id
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Template not found")

    await db.execute(
        update(UserTemplate)
        .where(UserTemplate.user_id == current_user.id)
        .values(is_default=False)
    )
    target.is_default = True
    await db.flush()
    await db.refresh(target)
    return _tpl_dict(target)


@router.put("/{template_id}")
async def update_template(template_id: UUID, body: TemplateUpdateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserTemplate).where(UserTemplate.id == template_id, UserTemplate.user_id == current_user.id))
    t = result.scalar_one_or_none()
    if not t: raise HTTPException(status_code=404, detail="Template not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(t, field, value)
    await db.flush()
    await db.refresh(t)
    return _tpl_dict(t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    force: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a template.

    By default, refuses with 409 if any exports still reference it — the
    DB has ON DELETE CASCADE, which would silently wipe all dependent
    exports. Pass ?force=true to accept the cascade.
    """
    result = await db.execute(
        select(UserTemplate).where(
            UserTemplate.id == template_id, UserTemplate.user_id == current_user.id
        )
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    if not force:
        attached = (
            await db.execute(
                select(func.count()).select_from(UserExport).where(UserExport.template_id == template_id)
            )
        ).scalar() or 0
        if attached > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Template is still used by {attached} export(s). "
                    "Re-apply a different template to those exports first, "
                    "or pass ?force=true to delete everything."
                ),
            )
    await db.delete(t)


@router.post("/{template_id}/upload-logo")
async def upload_logo(
    template_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserTemplate).where(
            UserTemplate.id == template_id, UserTemplate.user_id == current_user.id
        )
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "png"
    if ext not in _ALLOWED_LOGO_EXT:
        raise HTTPException(status_code=400, detail="Unsupported logo format")

    content = await file.read()
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Logo too large (max 5 MB)")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    key = f"{current_user.id}/{template_id}/{uuid4().hex}.{ext}"
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
    t.logo_minio_key = f"{LOGOS_BUCKET}/{key}"
    await db.flush()
    await db.refresh(t)
    return _tpl_dict(t)


def _tpl_dict(t: UserTemplate) -> dict:
    return {
        "id": str(t.id), "user_id": str(t.user_id), "template_name": t.template_name,
        "logo_minio_key": t.logo_minio_key, "logo_position": t.logo_position,
        "headline_defaults": t.headline_defaults, "subtitle_defaults": t.subtitle_defaults,
        "text_layers": t.text_layers or [],
        "background_color": t.background_color, "is_default": t.is_default,
        "created_at": str(t.created_at), "updated_at": str(t.updated_at),
    }
