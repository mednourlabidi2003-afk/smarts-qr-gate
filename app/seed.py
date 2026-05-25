from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .database import create_db_engine, create_session_factory, init_db, session_scope
from .models import ReservationRecord


def seed_sample_data(session_factory: sessionmaker[Session]) -> None:
    now = datetime.now(timezone.utc)
    sample_reservations = [
        {
            "reservation_id": "SMARTSDEMO1",
            "spot_id": "A12",
            "user_id": "Ahmed",
            "start_time": now - timedelta(minutes=15),
            "end_time": now + timedelta(hours=2),
            "plate": "123TUN4567",
        },
        {
            "reservation_id": "SMARTSDEMO2",
            "spot_id": "B05",
            "user_id": "Sami",
            "start_time": now + timedelta(minutes=25),
            "end_time": now + timedelta(hours=1, minutes=25),
            "plate": "987TUN1111",
        },
        {
            "reservation_id": "SMARTSDEMO3",
            "spot_id": "C03",
            "user_id": "Ali",
            "start_time": now - timedelta(hours=3),
            "end_time": now - timedelta(minutes=30),
            "plate": "555TUN2222",
        },
    ]

    with session_scope(session_factory) as session:
        existing = {
            r.reservation_id: r
            for r in session.scalars(select(ReservationRecord)).all()
        }
        for payload in sample_reservations:
            if payload["reservation_id"] in existing:
                record = existing[payload["reservation_id"]]
                record.start_time = payload["start_time"]
                record.end_time = payload["end_time"]
                record.used_at = None
            else:
                session.add(ReservationRecord(**payload))


def main() -> None:
    engine = create_db_engine()
    session_factory = create_session_factory(engine)
    init_db(engine)
    seed_sample_data(session_factory)
    print("Sample reservations inserted.")


if __name__ == "__main__":
    main()
