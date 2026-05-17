from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from .database import session_scope
from .models import AccessLog
from .schemas import AccessLogRead, GateStats
from .validator import BookingValidator, ValidationResult, normalize_ticket_code
from .websocket_manager import WebSocketManager


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class GateState:
    gate_status: str = "CLOSED"
    barrier_angle: int = 0
    last_ticket_code: str | None = None
    last_qr_payload: str | None = None
    validation_result: str = "SYSTEM READY"
    payment_status: str | None = None
    spot_number: str | None = None
    user_name: str | None = None
    timestamp: datetime = field(default_factory=utcnow)
    reason: str | None = "Waiting for QR ticket scan."
    access_granted: bool | None = None


class GateManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        validator: BookingValidator,
        websocket_manager: WebSocketManager,
        auto_close_seconds: int = 5,
        log_limit: int = 100,
    ) -> None:
        self.session_factory = session_factory
        self.validator = validator
        self.websocket_manager = websocket_manager
        self.auto_close_seconds = auto_close_seconds
        self.log_limit = log_limit

        self.state = GateState()
        self._lock = asyncio.Lock()
        self._auto_close_task: asyncio.Task | None = None

    async def validate_ticket(self, ticket_code: str | None = None, qr_data: str | None = None) -> ValidationResult:
        result = self.validator.validate_ticket(ticket_code=ticket_code, qr_data=qr_data)

        fallback_ticket = normalize_ticket_code(ticket_code or qr_data or "")
        async with self._lock:
            self.state.last_ticket_code = result.normalized_ticket_code or fallback_ticket or None
            self.state.last_qr_payload = result.qr_data or qr_data or None
            self.state.payment_status = result.payment_status
            self.state.spot_number = result.spot_id
            self.state.user_name = result.user_name
            self.state.timestamp = result.timestamp
            self.state.reason = result.reason
            self.state.access_granted = result.access_granted
            self.state.validation_result = "ACCESS GRANTED" if result.access_granted else "ACCESS DENIED"

        if result.access_granted:
            await self._open_gate(
                ticket_code=result.normalized_ticket_code,
                qr_payload=result.qr_data,
                reason=result.reason,
                payment_status=result.payment_status,
                spot_number=result.spot_id,
                user_name=result.user_name,
                validation_result="ACCESS GRANTED",
                access_granted=True,
                log_result="granted",
                log_action="opened",
            )
        else:
            await self._set_closed_banner()
            self._append_access_log(
                ticket_code=result.normalized_ticket_code or None,
                result="denied",
                reason=result.reason,
                gate_action="stayed_closed",
            )
            await self.broadcast_snapshot()

        return result

    async def manual_open(self, ticket_code: str | None = None, reason: str = "manual_override") -> dict:
        normalized_ticket = normalize_ticket_code(ticket_code) if ticket_code else None
        await self._open_gate(
            ticket_code=normalized_ticket,
            qr_payload=None,
            reason=reason,
            payment_status="manual",
            spot_number="-",
            user_name="Operator",
            validation_result="MANUAL OPEN",
            access_granted=True,
            log_result="manual",
            log_action="opened",
        )
        return await self.status_payload()

    async def manual_close(self, reason: str = "manual_close") -> dict:
        await self._close_gate(reason=reason, log_result="manual", log_action="closed")
        return await self.status_payload()

    async def clear_log(self) -> int:
        with session_scope(self.session_factory) as session:
            session.execute(delete(AccessLog))

        await self.broadcast_snapshot()
        return 0

    async def status_payload(self) -> dict:
        async with self._lock:
            payload = {
                "gate_status": self.state.gate_status,
                "barrier_angle": self.state.barrier_angle,
                "last_ticket_code": self.state.last_ticket_code,
                "last_qr_payload": self.state.last_qr_payload,
                "validation_result": self.state.validation_result,
                "payment_status": self.state.payment_status,
                "spot_number": self.state.spot_number,
                "user_name": self.state.user_name,
                "timestamp": self.state.timestamp.isoformat(),
                "reason": self.state.reason,
                "access_granted": self.state.access_granted,
                "auto_close_seconds": self.auto_close_seconds,
            }

        payload["stats"] = self.stats_payload()
        return payload

    def access_logs(self, limit: int | None = None) -> list[dict]:
        with session_scope(self.session_factory) as session:
            records = (
                session.scalars(
                    select(AccessLog)
                    .order_by(AccessLog.timestamp.desc())
                    .limit(limit or self.log_limit)
                )
                .unique()
                .all()
            )
            return [
                AccessLogRead.model_validate(record).model_dump(mode="json")
                for record in records
            ]

    def stats_payload(self) -> dict:
        with session_scope(self.session_factory) as session:
            total_events = session.scalar(select(func.count(AccessLog.id))) or 0
            granted_count = session.scalar(
                select(func.count(AccessLog.id)).where(AccessLog.result == "granted")
            ) or 0
            denied_count = session.scalar(
                select(func.count(AccessLog.id)).where(AccessLog.result == "denied")
            ) or 0
            manual_actions = session.scalar(
                select(func.count(AccessLog.id)).where(AccessLog.result == "manual")
            ) or 0

        return GateStats(
            total_events=int(total_events),
            granted_count=int(granted_count),
            denied_count=int(denied_count),
            manual_actions=int(manual_actions),
        ).model_dump()

    async def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "status": await self.status_payload(),
            "logs": self.access_logs(),
        }

    async def broadcast_snapshot(self) -> None:
        await self.websocket_manager.broadcast_json(await self.snapshot())

    async def _set_closed_banner(self) -> None:
        async with self._lock:
            if self.state.gate_status != "OPEN":
                self.state.gate_status = "CLOSED"
                self.state.barrier_angle = 0

    async def _open_gate(
        self,
        ticket_code: str | None,
        qr_payload: str | None,
        reason: str,
        payment_status: str | None,
        spot_number: str | None,
        user_name: str | None,
        validation_result: str,
        access_granted: bool | None,
        log_result: str,
        log_action: str,
    ) -> None:
        async with self._lock:
            if self._auto_close_task and not self._auto_close_task.done():
                self._auto_close_task.cancel()

            self.state.gate_status = "OPEN"
            self.state.barrier_angle = 90
            self.state.last_ticket_code = ticket_code
            self.state.last_qr_payload = qr_payload
            self.state.payment_status = payment_status
            self.state.spot_number = spot_number
            self.state.user_name = user_name
            self.state.timestamp = utcnow()
            self.state.reason = reason
            self.state.access_granted = access_granted
            self.state.validation_result = validation_result
            self._auto_close_task = asyncio.create_task(self._auto_close_after_delay())

        self._append_access_log(
            ticket_code=ticket_code,
            result=log_result,
            reason=reason,
            gate_action=log_action,
        )
        await self.broadcast_snapshot()

    async def _close_gate(self, reason: str, log_result: str, log_action: str) -> None:
        async with self._lock:
            if self._auto_close_task and not self._auto_close_task.done():
                self._auto_close_task.cancel()
                self._auto_close_task = None

            self.state.gate_status = "CLOSED"
            self.state.barrier_angle = 0
            self.state.timestamp = utcnow()
            self.state.reason = reason

        self._append_access_log(
            ticket_code=self.state.last_ticket_code,
            result=log_result,
            reason=reason,
            gate_action=log_action,
        )
        await self.broadcast_snapshot()

    async def _auto_close_after_delay(self) -> None:
        try:
            await asyncio.sleep(self.auto_close_seconds)
            async with self._lock:
                self.state.gate_status = "CLOSED"
                self.state.barrier_angle = 0
                self.state.timestamp = utcnow()
                self.state.reason = "auto_close"
            self._append_access_log(
                ticket_code=self.state.last_ticket_code,
                result="system",
                reason="auto_close",
                gate_action="closed",
            )
            await self.broadcast_snapshot()
        except asyncio.CancelledError:
            return

    def _append_access_log(self, ticket_code: str | None, result: str, reason: str, gate_action: str) -> None:
        with session_scope(self.session_factory) as session:
            session.add(
                AccessLog(
                    ticket_code=ticket_code,
                    result=result,
                    reason=reason,
                    gate_action=gate_action,
                )
            )
