from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import create_db_engine, create_session_factory, init_db, session_scope
from app.models import ReservationRecord
from app.validator import BookingValidator, normalize_plate, normalize_ticket_code, parse_qr_payload


@pytest.fixture()
def validator(tmp_path):
    db_path = tmp_path / "validator.db"
    engine = create_db_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
    init_db(engine)
    session_factory = create_session_factory(engine)

    now = datetime.now(timezone.utc)
    with session_scope(session_factory) as session:
        session.add_all(
            [
                ReservationRecord(
                    reservation_id="abc123ef",
                    spot_id="P1",
                    user_id="ahmed@example.com",
                    start_time=now - timedelta(minutes=15),
                    end_time=now + timedelta(hours=2),
                    plate="123TUN4567",
                ),
                ReservationRecord(
                    reservation_id="future456",
                    spot_id="P2",
                    user_id="sami@example.com",
                    start_time=now + timedelta(minutes=30),
                    end_time=now + timedelta(hours=3),
                    plate="987TUN1111",
                ),
            ]
        )

    yield BookingValidator(session_factory)
    engine.dispose()


def test_normalize_ticket_code_handles_mixed_separators() -> None:
    assert normalize_ticket_code("ab c1-23_ef") == "AB-C1-23-EF"


def test_normalize_plate_supports_tunisian_format() -> None:
    assert normalize_plate("123 TUN 4567") == "123TUN4567"


def test_parse_qr_payload_reads_multiline_ticket() -> None:
    payload = parse_qr_payload(
        "SMARTS PARKING\nSPOT: P1\nPLATE: 123 TUN 4567\nREF: abc123ef"
    )
    assert payload["reservation_id"] == "abc123ef"
    assert payload["spot_id"] == "P1"
    assert payload["plate"] == "123 TUN 4567"


def test_validate_ticket_grants_access_for_active_reservation(validator: BookingValidator) -> None:
    result = validator.validate_ticket(
        qr_data='{"reservation_id":"abc123ef","spot_id":"P1","plate":"123TUN4567"}'
    )
    assert result.access_granted is True
    assert result.reason == "valid_booking"
    assert result.normalized_ticket_code == "ABC123EF"


def test_validate_ticket_rejects_future_reservation(validator: BookingValidator) -> None:
    result = validator.validate_ticket(ticket_code="future456")
    assert result.access_granted is False
    assert result.reason == "booking_not_started"
