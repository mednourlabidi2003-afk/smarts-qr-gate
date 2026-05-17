from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TicketValidationRequest(BaseModel):
    ticket_code: Optional[str] = Field(default=None, min_length=3, max_length=128)
    qr_data: Optional[str] = Field(default=None, min_length=3, max_length=1024)

    @model_validator(mode="after")
    def validate_payload(self) -> "TicketValidationRequest":
        if self.ticket_code or self.qr_data:
            return self
        raise ValueError("Provide either ticket_code or qr_data.")


class GateActionRequest(BaseModel):
    ticket_code: Optional[str] = None
    reason: str = "manual_override"


class ClearLogResponse(BaseModel):
    cleared: bool
    remaining: int


class AccessLogRead(BaseModel):
    id: int
    timestamp: datetime
    ticket_code: Optional[str] = None
    result: str
    reason: str
    gate_action: str

    model_config = ConfigDict(from_attributes=True)


class GateStats(BaseModel):
    total_events: int = 0
    granted_count: int = 0
    denied_count: int = 0
    manual_actions: int = 0


class GateStatusResponse(BaseModel):
    gate_status: str
    barrier_angle: int
    last_ticket_code: Optional[str] = None
    last_qr_payload: Optional[str] = None
    validation_result: str
    payment_status: Optional[str] = None
    spot_number: Optional[str] = None
    user_name: Optional[str] = None
    timestamp: datetime
    reason: Optional[str] = None
    access_granted: Optional[bool] = None
    auto_close_seconds: int
    stats: GateStats


class GateActionResponse(BaseModel):
    message: str
    status: GateStatusResponse


class TicketValidationResponse(BaseModel):
    ticket_code: str
    normalized_ticket_code: str
    qr_data: Optional[str] = None
    access_granted: bool
    reason: str
    payment_status: Optional[str] = None
    booking_status: Optional[str] = None
    user_name: Optional[str] = None
    spot_number: Optional[str] = None
    gate_status: str
    timestamp: datetime


class HealthResponse(BaseModel):
    status: str
    database_ok: bool
    gate_status: str
    websocket_clients: int
