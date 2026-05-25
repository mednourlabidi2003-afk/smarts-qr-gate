from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .database import session_scope
from .models import ReservationRecord


ARABIC_DIGIT_MAP = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")
EASTERN_DIGIT_MAP = str.maketrans("\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9", "0123456789")
RESERVATION_KEYS = (
    "reservation_id",
    "reservationId",
    "ticket_code",
    "ticketCode",
    "ticket",
    "ref",
    "reference",
    "code",
)
PLATE_LINE_RE = re.compile(r"^PLATE\s*:\s*(.+)$", re.IGNORECASE)
SPOT_LINE_RE = re.compile(r"^SPOT(?:_ID)?\s*:\s*(.+)$", re.IGNORECASE)
REF_LINE_RE = re.compile(r"^(?:REF|REFERENCE|RESERVATION(?:_ID)?)\s*:\s*(.+)$", re.IGNORECASE)


def _strip_diacritics(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_ticket_code(value: str | None) -> str:
    if not value:
        return ""

    text = _strip_diacritics(value)
    text = text.translate(ARABIC_DIGIT_MAP).translate(EASTERN_DIGIT_MAP)
    text = text.upper().strip()
    text = re.sub(r"[^A-Z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def normalize_plate(value: str | None) -> str:
    if not value:
        return ""

    text = _strip_diacritics(value)
    text = text.translate(ARABIC_DIGIT_MAP).translate(EASTERN_DIGIT_MAP)
    text = text.upper()
    text = re.sub(r"\u062a\s*\u0648\s*\u0646\s*\u0633", "TUN", text)
    text = text.replace("\u062a\u0648\u0646\u0633", "TUN").replace("TN", "TUN")
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def parse_qr_payload(payload: str | None) -> dict[str, str]:
    raw_payload = (payload or "").strip()
    if not raw_payload:
        return {}

    parsed: dict[str, str] = {"raw": raw_payload}

    try:
        loaded = json.loads(raw_payload)
    except json.JSONDecodeError:
        loaded = None

    if isinstance(loaded, dict):
        for key in RESERVATION_KEYS:
            value = loaded.get(key)
            if isinstance(value, str) and value.strip():
                parsed["reservation_id"] = value.strip()
                break
        for key in ("plate", "plate_number"):
            value = loaded.get(key)
            if isinstance(value, str) and value.strip():
                parsed["plate"] = value.strip()
                break
        for key in ("spot_id", "spotId", "spot"):
            value = loaded.get(key)
            if isinstance(value, str) and value.strip():
                parsed["spot_id"] = value.strip()
                break
        return parsed

    if "://" in raw_payload:
        parsed_url = urlparse(raw_payload)
        query = parse_qs(parsed_url.query, keep_blank_values=False)
        for key in RESERVATION_KEYS:
            values = query.get(key)
            if values:
                parsed["reservation_id"] = values[0].strip()
                break
        if "reservation_id" not in parsed and parsed_url.path:
            path_parts = [part for part in parsed_url.path.split("/") if part]
            if path_parts:
                parsed["reservation_id"] = path_parts[-1].strip()
        return parsed

    if "=" in raw_payload and "\n" not in raw_payload:
        query = parse_qs(raw_payload, keep_blank_values=False)
        for key in RESERVATION_KEYS:
            values = query.get(key)
            if values:
                parsed["reservation_id"] = values[0].strip()
                break
        values = query.get("plate")
        if values:
            parsed["plate"] = values[0].strip()
        values = query.get("spot_id") or query.get("spot")
        if values:
            parsed["spot_id"] = values[0].strip()
        return parsed

    for line in raw_payload.splitlines():
        item = line.strip()
        if not item:
            continue
        ref_match = REF_LINE_RE.match(item)
        if ref_match:
            parsed["reservation_id"] = ref_match.group(1).strip()
            continue
        plate_match = PLATE_LINE_RE.match(item)
        if plate_match:
            parsed["plate"] = plate_match.group(1).strip()
            continue
        spot_match = SPOT_LINE_RE.match(item)
        if spot_match:
            parsed["spot_id"] = spot_match.group(1).strip()
            continue

    if "reservation_id" not in parsed:
        parsed["reservation_id"] = raw_payload
    return parsed


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(slots=True)
class ValidationResult:
    ticket_code: str
    normalized_ticket_code: str
    access_granted: bool
    reason: str
    qr_data: str | None = None
    payment_status: str | None = None
    booking_status: str | None = None
    spot_id: str | None = None
    user_name: str | None = None
    booking_id: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BookingValidator:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def validate_ticket(self, ticket_code: str | None = None, qr_data: str | None = None) -> ValidationResult:
        now = datetime.now(timezone.utc)
        raw_qr = (qr_data or "").strip()
        raw_ticket = (ticket_code or "").strip()

        payload = parse_qr_payload(raw_qr or raw_ticket)
        reservation_ref = payload.get("reservation_id", raw_ticket)
        normalized_ref = normalize_ticket_code(reservation_ref)
        normalized_plate = normalize_plate(payload.get("plate"))
        normalized_spot = normalize_ticket_code(payload.get("spot_id"))

        if not normalized_ref:
            return ValidationResult(
                ticket_code=reservation_ref,
                normalized_ticket_code="",
                access_granted=False,
                reason="invalid_ticket_format",
                qr_data=raw_qr or None,
                timestamp=now,
            )

        with session_scope(self.session_factory) as session:
            reservation = session.scalar(
                select(ReservationRecord).where(func.upper(ReservationRecord.reservation_id) == normalized_ref)
            )

            if reservation is None:
                return ValidationResult(
                    ticket_code=reservation_ref,
                    normalized_ticket_code=normalized_ref,
                    access_granted=False,
                    reason="ticket_not_found",
                    qr_data=raw_qr or None,
                    timestamp=now,
                )

            start_time = ensure_utc(reservation.start_time)
            end_time = ensure_utc(reservation.end_time)

            if normalized_spot and normalize_ticket_code(reservation.spot_id) != normalized_spot:
                return ValidationResult(
                    ticket_code=reservation_ref,
                    normalized_ticket_code=normalized_ref,
                    access_granted=False,
                    reason="spot_mismatch",
                    qr_data=raw_qr or None,
                    payment_status="paid",
                    booking_status="active",
                    spot_id=reservation.spot_id,
                    user_name=reservation.user_id,
                    booking_id=reservation.id,
                    timestamp=now,
                )

            db_plate = normalize_plate(reservation.plate)
            if normalized_plate and db_plate and normalized_plate != db_plate:
                return ValidationResult(
                    ticket_code=reservation_ref,
                    normalized_ticket_code=normalized_ref,
                    access_granted=False,
                    reason="plate_mismatch",
                    qr_data=raw_qr or None,
                    payment_status="paid",
                    booking_status="active",
                    spot_id=reservation.spot_id,
                    user_name=reservation.user_id,
                    booking_id=reservation.id,
                    timestamp=now,
                )

            if now < start_time:
                return ValidationResult(
                    ticket_code=reservation_ref,
                    normalized_ticket_code=normalized_ref,
                    access_granted=False,
                    reason="booking_not_started",
                    qr_data=raw_qr or None,
                    payment_status="paid",
                    booking_status="upcoming",
                    spot_id=reservation.spot_id,
                    user_name=reservation.user_id,
                    booking_id=reservation.id,
                    timestamp=now,
                )

            if now > end_time:
                return ValidationResult(
                    ticket_code=reservation_ref,
                    normalized_ticket_code=normalized_ref,
                    access_granted=False,
                    reason="booking_expired",
                    qr_data=raw_qr or None,
                    payment_status="paid",
                    booking_status="expired",
                    spot_id=reservation.spot_id,
                    user_name=reservation.user_id,
                    booking_id=reservation.id,
                    timestamp=now,
                )

            if reservation.used_at is not None:
                return ValidationResult(
                    ticket_code=reservation_ref,
                    normalized_ticket_code=normalized_ref,
                    access_granted=False,
                    reason="ticket_already_used",
                    qr_data=raw_qr or None,
                    payment_status="paid",
                    booking_status="used",
                    spot_id=reservation.spot_id,
                    user_name=reservation.user_id,
                    booking_id=reservation.id,
                    timestamp=now,
                )

            # Mark the ticket as used atomically before committing.
            reservation.used_at = now
            spot_id = reservation.spot_id
            user_id = reservation.user_id
            rec_id = reservation.id

        return ValidationResult(
            ticket_code=reservation_ref,
            normalized_ticket_code=normalized_ref,
            access_granted=True,
            reason="valid_booking",
            qr_data=raw_qr or None,
            payment_status="paid",
            booking_status="active",
            spot_id=spot_id,
            user_name=user_id,
            booking_id=rec_id,
            timestamp=now,
        )
