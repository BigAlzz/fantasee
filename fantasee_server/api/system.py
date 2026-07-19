"""Local application lifecycle controls.

Restart is a handoff rather than a detached Python fork.  The handoff opens
visible PowerShell terminals, waits for the current server to release 8765,
and starts one deterministic worker stack without duplicating port owners.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.production_runtime import production_database_path
from fantasee_server.production_store import ProductionStore


router = APIRouter(tags=["system"])
_restart_task: asyncio.Task[None] | None = None
RENDERING_MODES = {"basic", "gpu", "max"}
MANAGED_PORTS = (8765, 8188, 8189, 8190, 8191, 8192, 8193, 8194)


def _server_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalise_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode not in RENDERING_MODES:
        raise ValueError("rendering mode must be basic, gpu, or max")
    return mode


def _mode_plan(mode: str) -> list[dict[str, Any]]:
    mode = _normalise_mode(mode)
    workers = {
        "basic": [("cpu", "cpu 8189", 8189)],
        "gpu": [("gpu", "gpu1", 8188)],
        "max": [("gpu", "gpu1", 8188), ("cpu", "cpu 8189", 8189)],
    }[mode]
    return [{"name": "server", "command": "server", "port": 8765}] + [
        {"name": kind, "command": command, "port": port}
        for kind, command, port in workers
    ]


def _powershell_executable() -> str:
    return "powershell.exe" if os.name == "nt" else "pwsh"


def _powershell_json(script: str) -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _port_owner(port: int) -> dict[str, Any] | None:
    """Return the listening PID and command line for a managed port."""
    script = (
        f"$connection = Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
        "-ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($connection) { $process = Get-CimInstance Win32_Process "
        "-Filter ('ProcessId = ' + $connection.OwningProcess) | Select-Object -First 1 "
        "Name,CommandLine,ProcessId; $process | ConvertTo-Json -Compress }"
    )
    return _powershell_json(script)


def _owner_text(owner: dict[str, Any] | None) -> str:
    if not owner:
        return ""
    return f"{owner.get('Name') or ''} {owner.get('CommandLine') or ''}".lower()


def _is_local_comfy_owner(owner: dict[str, Any] | None) -> bool:
    text = _owner_text(owner)
    return "comfyui" in text or " main.py" in text or "\\main.py" in text


def _is_local_server_owner(owner: dict[str, Any] | None) -> bool:
    text = _owner_text(owner)
    return "server.py" in text or "fantasee" in text


def _managed_port_conflicts() -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    current_pid = os.getpid()
    for port in MANAGED_PORTS:
        owner = _port_owner(port)
        if not owner:
            continue
        pid = int(owner.get("ProcessId") or owner.get("Id") or 0)
        if pid == current_pid:
            continue
        if port == 8765 and _is_local_server_owner(owner):
            conflicts.append({"port": port, "pid": pid, "reason": "duplicate Fantasee server"})
        elif port != 8765 and not _is_local_comfy_owner(owner):
            conflicts.append({"port": port, "pid": pid, "reason": "unknown process owns managed port"})
    return conflicts


def _terminate_local_comfy_workers() -> list[int]:
    stopped: list[int] = []
    for port in MANAGED_PORTS:
        if port == 8765:
            continue
        owner = _port_owner(port)
        if not owner or not _is_local_comfy_owner(owner):
            continue
        pid = int(owner.get("ProcessId") or owner.get("Id") or 0)
        if not pid:
            continue
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode == 0:
                stopped.append(pid)
        except (OSError, subprocess.SubprocessError):
            continue
    return stopped


def _server_environment(mode: str) -> dict[str, str]:
    env = os.environ.copy()
    env["FANTASEE_RENDERING_MODE"] = mode
    env["FANTASEE_AUTO_SPAWN_CPU"] = "0"
    env["COMFYUI_URLS"] = {
        "basic": "http://127.0.0.1:8189",
        "gpu": "http://127.0.0.1:8188",
        "max": "http://127.0.0.1:8188,http://127.0.0.1:8189",
    }[mode]
    return env


def _launch_terminal(service: dict[str, Any], mode: str) -> None:
    bat = str((_server_root() / "start.bat").resolve()).replace("'", "''")
    port = int(service["port"])
    command = service["command"]
    title = f"Fantasee {service['name'].upper()} :{port}".replace("'", "''")
    if service["name"] == "server":
        wait = (
            f"while (Get-NetTCPConnection -LocalPort {port} -State Listen "
            "-ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 500 }; "
        )
    else:
        wait = ""
    ps_command = f"$Host.UI.RawUI.WindowTitle = '{title}'; {wait}& '{bat}' {command}"
    env = _server_environment(mode) if service["name"] == "server" else os.environ.copy()
    kwargs: dict[str, Any] = {
        "args": [
            _powershell_executable(), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-NoExit", "-Command", ps_command,
        ],
        "cwd": str(_server_root()),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(**kwargs)


async def _restart_after_response(mode: str) -> None:
    await asyncio.sleep(0.75)
    await asyncio.to_thread(_terminate_local_comfy_workers)
    for service in _mode_plan(mode):
        if service["name"] != "server":
            await asyncio.to_thread(_launch_terminal, service, mode)
    await asyncio.sleep(0.25)
    await asyncio.to_thread(_launch_terminal, _mode_plan(mode)[0], mode)
    # The server terminal is waiting for 8765, so this process can safely
    # release the port without racing its replacement.
    os._exit(0)


@router.post("/api/system/restart")
async def restart_everything(body: dict[str, Any] | None = Body(default=None)):
    """Restart the app and the selected local worker stack once."""
    global _restart_task
    if _restart_task and not _restart_task.done():
        raise HTTPException(status_code=409, detail="A full restart is already in progress")
    payload = body or {}
    try:
        with ProductionStore(production_database_path()) as store:
            mode = _normalise_mode(payload.get("rendering_mode") or store.rendering_mode())
            if payload.get("rendering_mode"):
                store.set_rendering_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conflicts = _managed_port_conflicts()
    if conflicts:
        raise HTTPException(status_code=409, detail={"message": "Restart blocked by existing port owners", "conflicts": conflicts})
    _restart_task = asyncio.create_task(_restart_after_response(mode))
    return {
        "accepted": True,
        "rendering_mode": mode,
        "services": _mode_plan(mode),
        "message": "PowerShell terminals are starting the selected Studio stack.",
    }
