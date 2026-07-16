"""WebSocket endpoint for live progress updates.

The single ``/ws`` connection is used by the frontend to stream
``task_update`` events for every background task. The server keeps
a list of connected clients and ``_broadcast_ws_json`` in
``fantasee_server.state`` fans payloads out to all of them.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from fantasee_server.security import require_websocket_operator
from fantasee_server.state import _websocket_clients


router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        require_websocket_operator(websocket)
    except Exception:
        await websocket.close(code=1008, reason="Operator authentication required")
        return
    await websocket.accept()
    _websocket_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages (ping, etc.)
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        _websocket_clients.remove(websocket)
    except Exception:
        if websocket in _websocket_clients:
            _websocket_clients.remove(websocket)
