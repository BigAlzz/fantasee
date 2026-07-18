"""Security boundaries shared by the HTTP API and provider clients."""

from __future__ import annotations

import ipaddress
import os
import secrets
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit

from fastapi import HTTPException, Request, WebSocket


DEFAULT_PROVIDER_HOSTS = frozenset({"token-plan-sgp.xiaomimimo.com", "api.unsplash.com"})
LOOPBACK_HOSTS = frozenset({"localhost"})
MAX_PROVIDER_URL_LENGTH = 2048


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]").rstrip(".")
    if normalized in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def authorize_client(client_host: str | None, authorization: str | None) -> None:
    """Require an operator token for non-loopback or explicitly secured use.

    The desktop UI remains usable on loopback by default. A server exposed on
    a LAN or through a proxy must set ``FANTASEE_API_TOKEN``; setting
    ``FANTASEE_REQUIRE_AUTH=1`` requires that token even for loopback clients.
    The client address is taken from the socket, never from forwarded headers.
    """
    token = os.environ.get("FANTASEE_API_TOKEN", "").strip()
    loopback = _is_loopback_host(client_host or "")
    if loopback and not _truthy(os.environ.get("FANTASEE_REQUIRE_AUTH")):
        return
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Operator authentication is required. Set FANTASEE_API_TOKEN.",
        )
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(presented, token):
        raise HTTPException(status_code=401, detail="Operator authentication required")


def require_operator(request: Request) -> None:
    """FastAPI dependency for privileged HTTP routes."""
    authorize_client(
        request.client.host if request.client else None,
        request.headers.get("authorization"),
    )


def require_websocket_operator(websocket: WebSocket) -> None:
    """Authorize the live progress WebSocket using the same policy."""
    authorize_client(
        websocket.client.host if websocket.client else None,
        websocket.headers.get("authorization"),
    )


def _allowed_provider_hosts() -> frozenset[str]:
    configured = os.environ.get("FANTASEE_ALLOWED_PROVIDER_HOSTS", "")
    hosts = {item.strip().lower().rstrip(".") for item in configured.split(",") if item.strip()}
    return frozenset(hosts or DEFAULT_PROVIDER_HOSTS)


def _address_is_unsafe(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return parsed.is_private or parsed.is_link_local or parsed.is_reserved or parsed.is_multicast or parsed.is_unspecified


def _resolved_addresses(host: str, port: int | None) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"provider host cannot be resolved: {host}") from exc
    addresses = sorted({info[4][0].split("%", 1)[0] for info in infos})
    if not addresses:
        raise ValueError(f"provider host cannot be resolved: {host}")
    return addresses


def _validate_provider_parts(
    parts: SplitResult,
    *,
    kind: str,
    resolve_dns: bool,
) -> str:
    if parts.scheme not in {"http", "https"}:
        raise ValueError("provider URL must use http or https")
    if parts.username or parts.password:
        raise ValueError("provider URL must not contain embedded credentials")
    if parts.query or parts.fragment:
        raise ValueError("provider URL must not contain a query or fragment")
    try:
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError as exc:
        raise ValueError("provider URL has an invalid port") from exc
    if not host:
        raise ValueError("provider URL must include a host")
    loopback = _is_loopback_host(host)
    if not loopback:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if host not in _allowed_provider_hosts():
                raise ValueError(f"provider host is not allowlisted: {host}")
            addresses = _resolved_addresses(host, port) if resolve_dns else []
        else:
            addresses = [host]
        if any(_address_is_unsafe(address) for address in addresses):
            raise ValueError("provider URL resolves to a private or otherwise unsafe address")
    if kind == "comfyui" and not loopback and host not in _allowed_provider_hosts():
        raise ValueError("ComfyUI must use a loopback or explicitly allowlisted host")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def validate_provider_url(
    raw_url: str,
    *,
    kind: str = "provider",
    resolve_dns: bool = True,
) -> str:
    """Validate and normalize a provider base URL before it is persisted/used."""
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("provider URL is required")
    if len(raw_url) > MAX_PROVIDER_URL_LENGTH:
        raise ValueError("provider URL is too long")
    try:
        parts = urlsplit(raw_url.strip())
    except ValueError as exc:
        raise ValueError("provider URL is malformed") from exc
    return _validate_provider_parts(parts, kind=kind, resolve_dns=resolve_dns)


def validate_provider_urls(raw_urls: str, *, resolve_dns: bool = True) -> str:
    """Validate a comma-separated ComfyUI worker list."""
    urls = [item.strip() for item in str(raw_urls or "").split(",") if item.strip()]
    if not urls:
        raise ValueError("at least one ComfyUI URL is required")
    return ",".join(
        validate_provider_url(url, kind="comfyui", resolve_dns=resolve_dns)
        for url in urls
    )
