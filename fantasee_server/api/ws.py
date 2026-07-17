"""WebSocket endpoint for live progress updates.

The single ``/ws`` connection is used by the frontend to stream
``task_update`` events for every background task. The server keeps
a list of connected clients and ``_broadcast_ws_json`` in
``fantasee_server.state`` fans payloads out to all of them.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from fantasee_server.production_runtime import production_database_path
from fantasee_server.production_store import ProductionStore
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
            if data == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            try:
                message = json.loads(data)
            except (TypeError, json.JSONDecodeError):
                continue
            if message.get("type") != "resume" or not message.get("run_id"):
                continue
            run_id = str(message["run_id"])
            try:
                after_sequence = max(0, int(message.get("after_sequence", 0)))
            except (TypeError, ValueError):
                after_sequence = 0
            with ProductionStore(production_database_path()) as store:
                events = store.list_events(run_id, after_sequence=after_sequence)
            await websocket.send_json({
                "type": "production.replay",
                "run_id": run_id,
                "events": [
                    {
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "payload": event.payload,
                        "created_at": event.created_at,
                    }
                    for event in events
                ],
                "next_sequence": events[-1].sequence if events else after_sequence,
            })
    except WebSocketDisconnect:
        _websocket_clients.remove(websocket)
    except Exception:
        if websocket in _websocket_clients:
            _websocket_clients.remove(websocket)
