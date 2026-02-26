from sqlalchemy import String, Float, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from typing import Optional

class Base(DeclarativeBase):
    pass


class Abbreviation(Base):
    __tablename__ = "abbreviations"

    short: Mapped[str] = mapped_column(String(100), primary_key=True)
    long: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    updated_at: Mapped[Optional[object]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
