from typing import TYPE_CHECKING, List
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.theme_page import ThemePage

class Niche(UUIDMixin, Base):
    __tablename__ = "niches"
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    theme_pages: Mapped[List["ThemePage"]] = relationship("ThemePage", back_populates="niche")
