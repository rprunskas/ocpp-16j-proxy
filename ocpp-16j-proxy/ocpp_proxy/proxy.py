from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from ocpp import messages
from websockets.asyncio.client import ClientConnection, connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed, WebSocketException

OCPP_SUBPROTOCOL = "ocpp1.6"
LOGGER = logging.getLogger("ocpp_proxy")


class Direction(StrEnum):
    CHARGE_POINT_TO_CENTRAL_SYSTEM = "charge_point_to_central_system"
    CENTRAL_SYSTEM_TO_CHARGE_POINT = "central_system_to_charge_point"

    @property
    def opposite(self) -> Direction:
        if self is Direction.CHARGE_POINT_TO_CENTRAL_SYSTEM:
            return Direction.CENTRAL_SYSTEM_TO_CHARGE_POINT
        return Direction.CHARGE_POINT_TO_CENTRAL_SYSTEM


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    upstream_url: str
    listen_host: str = "0.0.0.0"
    listen_port: int = 9000
    log_level: str = "INFO"
    max_message_size: int = 1_048_576
    ping_interval: float = 20.0
    ping_timeout: float = 20.0
    open_timeout: float = 10.0
    upstream_authorization: str | None = None
    forward_authorization: bool = True

    def __post_init__(self) -> None:
        parts = urlsplit(self.upstream_url)
        if parts.scheme not in {"ws", "wss"} or not parts.netloc:
            raise ValueError("upstream_url must be an absolute ws:// or wss:// URL")
        if not 1 <= self.listen_port <= 65535:
            raise ValueError("listen_port must be between 1 and 65535")
        if self.max_message_size <= 0:
            raise ValueError("max_message_size must be positive")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("log_level must be DEBUG, INFO, WARNING, or ERROR")

    @classmethod
    def from_env(
        cls,
        *,
        upstream_url: str | None = None,
        listen_host: str | None = None,
        listen_port: int | None = None,
        log_level: str | None = None,
    ) -> ProxyConfig:
        resolved_upstream = upstream_url or os.getenv("OCPP_UPSTREAM_URL")
        if not resolved_upstream:
            raise ValueError("set OCPP_UPSTREAM_URL or pass --upstream")

        return cls(
            upstream_url=resolved_upstream,
            listen_host=listen_host or os.getenv("OCPP_LISTEN_HOST", "0.0.0.0"),
            listen_port=(
                listen_port
                if listen_port is not None
                else _env_int("OCPP_LISTEN_PORT", 9000)
            ),
            log_level=(log_level or os.getenv("OCPP_LOG_LEVEL", "INFO")).upper(),
            max_message_size=_env_int("OCPP_MAX_MESSAGE_SIZE", 1_048_576),
            ping_interval=_env_float("OCPP_PING_INTERVAL", 20.0),
            ping_timeout=_env_float("OCPP_PING_TIMEOUT", 20.0),
            open_timeout=_env_float("OCPP_OPEN_TIMEOUT", 10.0),
            upstream_authorization=os.getenv("OCPP_UPSTREAM_AUTHORIZATION"),
            forward_authorization=_env_bool("OCPP_FORWARD_AUTHORIZATION", True),
        )


@dataclass(frozen=True, slots=True)
class PendingCall:
    action: str
    started_at: float
    request_direction: Direction


class OcppMessageLogger:
    """Decode OCPP envelopes and correlate responses with their calls."""

    def __init__(self, *, connection_id: str, charge_point_id: str) -> None:
        self.connection_id = connection_id
        self.charge_point_id = charge_point_id
        self._pending: dict[tuple[Direction, str], PendingCall] = {}

    def record(self, raw_message: str | bytes, direction: Direction) -> None:
        common = {
            "connection_id": self.connection_id,
            "charge_point_id": self.charge_point_id,
            "direction": direction.value,
        }

        if isinstance(raw_message, bytes):
            log_event(
                logging.WARNING,
                "non_text_websocket_frame",
                **common,
                size_bytes=len(raw_message),
            )
            return

        try:
            message = messages.unpack(raw_message)
        except Exception as exc:  # Relay malformed data unchanged; only logging is best-effort.
            log_event(
                logging.WARNING,
                "invalid_ocpp_frame",
                **common,
                error=str(exc),
                raw_message=raw_message,
            )
            return

        if isinstance(message, messages.Call):
            key = (direction.opposite, str(message.unique_id))
            previous = self._pending.get(key)
            if previous is not None:
                log_event(
                    logging.WARNING,
                    "duplicate_ocpp_unique_id",
                    **common,
                    unique_id=message.unique_id,
                    previous_action=previous.action,
                    action=message.action,
                )
            self._pending[key] = PendingCall(
                action=message.action,
                started_at=time.monotonic(),
                request_direction=direction,
            )
            log_event(
                logging.INFO,
                "ocpp_request",
                **common,
                message_type="CALL",
                unique_id=message.unique_id,
                action=message.action,
                payload=message.payload,
            )
            return

        pending = self._pending.pop((direction, str(message.unique_id)), None)
        response_fields: dict[str, Any] = {
            **common,
            "unique_id": message.unique_id,
            "action": pending.action if pending else None,
            "correlated": pending is not None,
        }
        if pending:
            response_fields["request_direction"] = pending.request_direction.value
            response_fields["latency_ms"] = round(
                (time.monotonic() - pending.started_at) * 1000, 3
            )

        if isinstance(message, messages.CallResult):
            log_event(
                logging.INFO,
                "ocpp_response",
                **response_fields,
                message_type="CALLRESULT",
                payload=message.payload,
            )
        elif isinstance(message, messages.CallError):
            log_event(
                logging.INFO,
                "ocpp_response",
                **response_fields,
                message_type="CALLERROR",
                error_code=message.error_code,
                error_description=message.error_description,
                error_details=message.error_details,
            )


class OcppProxy:
    def __init__(self, config: ProxyConfig) -> None:
        self.config = config

    async def run(self) -> None:
        log_event(
            logging.INFO,
            "proxy_started",
            listen_host=self.config.listen_host,
            listen_port=self.config.listen_port,
            upstream_url=self.config.upstream_url,
            subprotocol=OCPP_SUBPROTOCOL,
        )
        try:
            async with serve(
                self.handle_connection,
                self.config.listen_host,
                self.config.listen_port,
                subprotocols=[OCPP_SUBPROTOCOL],
                max_size=self.config.max_message_size,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,
            ) as server:
                await server.serve_forever()
        finally:
            log_event(logging.INFO, "proxy_stopped")

    async def handle_connection(self, charge_point: ServerConnection) -> None:
        connection_id = uuid.uuid4().hex
        request_path = charge_point.request.path
        charge_point_id = extract_charge_point_id(request_path)

        if charge_point.subprotocol != OCPP_SUBPROTOCOL:
            log_event(
                logging.WARNING,
                "connection_rejected",
                connection_id=connection_id,
                charge_point_id=charge_point_id,
                reason=f"Client must offer {OCPP_SUBPROTOCOL}",
            )
            await charge_point.close(
                code=1002, reason=f"The {OCPP_SUBPROTOCOL} subprotocol is required"
            )
            return

        if not charge_point_id:
            log_event(
                logging.WARNING,
                "connection_rejected",
                connection_id=connection_id,
                reason="Missing charge point identity in WebSocket path",
            )
            await charge_point.close(code=1008, reason="Missing charge point identity")
            return

        upstream_url = build_upstream_url(self.config.upstream_url, request_path)
        headers = self._upstream_headers(charge_point)
        log_event(
            logging.INFO,
            "charge_point_connected",
            connection_id=connection_id,
            charge_point_id=charge_point_id,
            remote_address=_format_address(charge_point.remote_address),
            upstream_url=upstream_url,
        )

        try:
            async with connect(
                upstream_url,
                subprotocols=[OCPP_SUBPROTOCOL],
                additional_headers=headers or None,
                open_timeout=self.config.open_timeout,
                max_size=self.config.max_message_size,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,
                proxy=None,
            ) as central_system:
                if central_system.subprotocol != OCPP_SUBPROTOCOL:
                    log_event(
                        logging.ERROR,
                        "upstream_subprotocol_rejected",
                        connection_id=connection_id,
                        charge_point_id=charge_point_id,
                        selected_subprotocol=central_system.subprotocol,
                    )
                    await charge_point.close(
                        code=1011, reason="Upstream did not select ocpp1.6"
                    )
                    return

                log_event(
                    logging.INFO,
                    "upstream_connected",
                    connection_id=connection_id,
                    charge_point_id=charge_point_id,
                    upstream_url=upstream_url,
                )
                tracker = OcppMessageLogger(
                    connection_id=connection_id,
                    charge_point_id=charge_point_id,
                )
                await self._relay_both_directions(
                    charge_point, central_system, tracker
                )
        except (OSError, TimeoutError, ConnectionClosed, WebSocketException) as exc:
            log_event(
                logging.ERROR,
                "upstream_connection_failed",
                connection_id=connection_id,
                charge_point_id=charge_point_id,
                upstream_url=upstream_url,
                error=str(exc),
            )
            await charge_point.close(code=1011, reason="Upstream connection failed")
        except Exception as exc:
            log_event(
                logging.ERROR,
                "connection_handler_failed",
                connection_id=connection_id,
                charge_point_id=charge_point_id,
                error=str(exc),
                exception_type=type(exc).__name__,
            )
            await charge_point.close(code=1011, reason="Proxy error")
        finally:
            log_event(
                logging.INFO,
                "charge_point_disconnected",
                connection_id=connection_id,
                charge_point_id=charge_point_id,
            )

    def _upstream_headers(self, charge_point: ServerConnection) -> list[tuple[str, str]]:
        if self.config.upstream_authorization:
            return [("Authorization", self.config.upstream_authorization)]
        if not self.config.forward_authorization:
            return []

        values = charge_point.request.headers.get_all("Authorization")
        return [("Authorization", values[0])] if values else []

    async def _relay_both_directions(
        self,
        charge_point: ServerConnection,
        central_system: ClientConnection,
        tracker: OcppMessageLogger,
    ) -> None:
        cp_to_cs = asyncio.create_task(
            self._relay(
                charge_point,
                central_system,
                tracker,
                Direction.CHARGE_POINT_TO_CENTRAL_SYSTEM,
            ),
            name="ocpp-charge-point-to-central-system",
        )
        cs_to_cp = asyncio.create_task(
            self._relay(
                central_system,
                charge_point,
                tracker,
                Direction.CENTRAL_SYSTEM_TO_CHARGE_POINT,
            ),
            name="ocpp-central-system-to-charge-point",
        )
        tasks = {cp_to_cs, cs_to_cp}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        completed = await asyncio.gather(*done, return_exceptions=True)
        failure = next(
            (result for result in completed if isinstance(result, BaseException)), None
        )
        if failure is not None:
            raise failure

        close_code, close_reason = completed[0]
        safe_code = close_code if close_code not in {None, 1005, 1006, 1015} else 1000
        await asyncio.gather(
            charge_point.close(code=safe_code, reason=close_reason or ""),
            central_system.close(code=safe_code, reason=close_reason or ""),
            return_exceptions=True,
        )

    @staticmethod
    async def _relay(
        source: ServerConnection | ClientConnection,
        destination: ServerConnection | ClientConnection,
        tracker: OcppMessageLogger,
        direction: Direction,
    ) -> tuple[int | None, str | None]:
        try:
            async for frame in source:
                tracker.record(frame, direction)
                await destination.send(frame)
        except ConnectionClosed as exc:
            return exc.code, exc.reason
        return source.close_code, source.close_reason


def build_upstream_url(base_url: str, incoming_path: str) -> str:
    path = urlsplit(incoming_path).path
    charge_point_path = path.lstrip("/")
    if not charge_point_path:
        raise ValueError("incoming WebSocket path has no charge point identity")

    if "{charge_point_id}" in base_url:
        return base_url.replace(
            "{charge_point_id}", quote(unquote(charge_point_path), safe="")
        )

    parts = urlsplit(base_url)
    joined_path = f"{parts.path.rstrip('/')}/{charge_point_path}"
    return urlunsplit((parts.scheme, parts.netloc, joined_path, parts.query, parts.fragment))


def extract_charge_point_id(request_path: str) -> str:
    path = urlsplit(request_path).path.strip("/")
    return unquote(path) if path else ""


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
    )


def log_event(level: int, event: str, **fields: Any) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level),
        "event": event,
        **fields,
    }
    LOGGER.log(level, json.dumps(record, separators=(",", ":"), default=str))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _format_address(address: Any) -> str | None:
    if address is None:
        return None
    if isinstance(address, tuple):
        return ":".join(str(part) for part in address[:2])
    return str(address)
