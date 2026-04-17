"""Niches — list available niches."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from models.niche import Niche

router = APIRouter(prefix="/api/niches", tags=["niches"])


@router.get("")
async def list_niches(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Niche).where(Niche.is_active == True).order_by(Niche.name))
    return [{"id": str(n.id), "name": n.name, "slug": n.slug} for n in result.scalars().all()]
