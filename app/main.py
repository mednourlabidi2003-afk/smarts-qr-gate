from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
import uvicorn

from .database import PROJECT_ROOT, create_db_engine, create_session_factory, init_db
from .gate_manager import GateManager
from .schemas import (
    ClearLogResponse,
    GateActionRequest,
    GateActionResponse,
    GateStatusResponse,
    HealthResponse,
    TicketValidationRequest,
    TicketValidationResponse,
)
from .seed import seed_sample_data
from .validator import BookingValidator
from .websocket_manager import WebSocketManager


load_dotenv(PROJECT_ROOT / ".env")

APP_NAME = os.getenv("APP_NAME", "SMARTS QR Gate")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8020"))
AUTO_SEED = os.getenv("AUTO_SEED", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTO_CLOSE_SECONDS = int(os.getenv("AUTO_CLOSE_SECONDS", "5"))
ACCESS_LOG_LIMIT = int(os.getenv("ACCESS_LOG_LIMIT", "100"))

engine = create_db_engine()
session_factory = create_session_factory(engine)
validator = BookingValidator(session_factory)
websocket_manager = WebSocketManager()
gate_manager = GateManager(
    session_factory=session_factory,
    validator=validator,
    websocket_manager=websocket_manager,
    auto_close_seconds=AUTO_CLOSE_SECONDS,
    log_limit=ACCESS_LOG_LIMIT,
)

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(engine)
    if AUTO_SEED:
        seed_sample_data(session_factory)
    yield
    engine.dispose()


app = FastAPI(
    title=APP_NAME,
    version="1.1.0",
    description="Software-based QR ticket gate simulator for SMARTS parking access validation.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": APP_NAME,
            "demo_valid_ticket": "SMARTSDEMO1",
            "demo_unpaid_ticket": "SMARTSDEMO2",
            "demo_expired_ticket": "SMARTSDEMO3",
        },
    )


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    status = await gate_manager.status_payload()
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        database_ok=database_ok,
        gate_status=status["gate_status"],
        websocket_clients=websocket_manager.client_count,
    )


@app.get("/api/gate/status", response_model=GateStatusResponse)
async def gate_status() -> GateStatusResponse:
    return GateStatusResponse.model_validate(await gate_manager.status_payload())


@app.post("/api/gate/open", response_model=GateActionResponse)
async def gate_open(payload: GateActionRequest) -> GateActionResponse:
    status = await gate_manager.manual_open(
        ticket_code=payload.ticket_code,
        reason=payload.reason or "manual_override",
    )
    return GateActionResponse(
        message="Virtual gate opened.",
        status=GateStatusResponse.model_validate(status),
    )


@app.post("/api/gate/close", response_model=GateActionResponse)
async def gate_close(payload: GateActionRequest) -> GateActionResponse:
    status = await gate_manager.manual_close(reason=payload.reason or "manual_close")
    return GateActionResponse(
        message="Virtual gate closed.",
        status=GateStatusResponse.model_validate(status),
    )


async def _validate_ticket_response(payload: TicketValidationRequest) -> TicketValidationResponse:
    result = await gate_manager.validate_ticket(ticket_code=payload.ticket_code, qr_data=payload.qr_data)
    status = await gate_manager.status_payload()
    return TicketValidationResponse(
        ticket_code=result.ticket_code,
        normalized_ticket_code=result.normalized_ticket_code,
        qr_data=result.qr_data,
        access_granted=result.access_granted,
        reason=result.reason,
        payment_status=result.payment_status,
        booking_status=result.booking_status,
        user_name=result.user_name,
        spot_number=result.spot_id,
        gate_status=status["gate_status"],
        timestamp=result.timestamp,
    )


@app.post("/api/validate-ticket", response_model=TicketValidationResponse)
async def validate_ticket(payload: TicketValidationRequest) -> TicketValidationResponse:
    return await _validate_ticket_response(payload)


@app.post("/api/validate-plate", response_model=TicketValidationResponse, include_in_schema=False)
async def validate_plate_compat(payload: TicketValidationRequest) -> TicketValidationResponse:
    return await _validate_ticket_response(payload)


@app.get("/api/access-log")
async def access_log() -> list[dict]:
    return gate_manager.access_logs()


@app.post("/api/access-log/clear", response_model=ClearLogResponse)
async def clear_access_log() -> ClearLogResponse:
    remaining = await gate_manager.clear_log()
    return ClearLogResponse(cleared=True, remaining=remaining)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket_manager.connect(websocket)
    try:
        await websocket.send_json(await gate_manager.snapshot())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
    except Exception:
        websocket_manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=False)
