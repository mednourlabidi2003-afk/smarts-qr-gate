from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReservationRecord(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    spot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    plate: Mapped[str | None] = mapped_column(String(64), nullable=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AccessLog(Base):
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    ticket_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    gate_action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
