from __future__ import annotations

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    @property
    def client_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast_json(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)

