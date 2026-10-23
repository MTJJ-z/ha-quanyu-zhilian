"""Transport-independent state machine for the existing CYD firmware.

MQTT ACLs are the trust boundary: telemetry is not cryptographically signed.
Retained telemetry is deliberately ignored until a live report arrives.
"""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from .const import (
    COLORS,
    COMMAND_TIMEOUT,
    HEARTBEAT_SECONDS,
    IR_MAX_RAW,
    MAX_PENDING,
    SCHEMA,
    STALE_SECONDS,
    SUPPORTED_FIRMWARE,
)


class GatewayError(Exception):
    """A command failed or its result cannot be established."""


def validate_identity(gateway_id: str, controller_id: str, token: str) -> None:
    """Reject topic wildcards and configurations the firmware cannot accept."""
    if not re.fullmatch(r"cyd_[0-9a-f]{12}", gateway_id):
        raise ValueError("invalid_gateway_id")
    if not 1 <= len(controller_id.encode("utf-8")) <= 128:
        raise ValueError("invalid_controller_id")
    if not 32 <= len(token.encode("utf-8")) <= 128:
        raise ValueError("invalid_binding_token")


def validate_room(room: str) -> None:
    """Firmware limits the room name to 32 UTF-8 bytes."""
    if not isinstance(room, str) or len(room.encode("utf-8")) > 32:
        raise ValueError("room_too_long")


def uint32(value: Any) -> bool:
    """JSON booleans are not integer sequence numbers."""
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


class GatewayProtocol:
    """Own one controller session, live state, configuration and pending ACKs."""

    def __init__(
        self,
        gateway_id: str,
        controller_id: str,
        token: str,
        publish: Callable[[str, dict[str, Any]], Awaitable[None]],
        changed: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        validate_identity(gateway_id, controller_id, token)
        self.gateway_id = gateway_id
        self.controller_id = controller_id
        self._token = token
        self._publish = publish
        self._changed = changed
        self._clock = clock
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._closed = False
        self.broker_connected = False
        self.boot_id: str | None = None
        self.session_id = uuid4().hex
        self.state: dict[str, Any] = {}
        self.last_seen: float | None = None
        self.last_sequence = -1
        self.room = "Unassigned"
        self.revision = 0
        self.configured = False
        self.configuration_error: str | None = None
        self.last_command_result = "none"
        self.last_ir_capture: dict[str, Any] | None = None
        self._heartbeat_sequence = 0
        self._command_sequence = 0
        self._heartbeat_at = float("-inf")
        self._config_at = float("-inf")
        self.ready_event = asyncio.Event()

    @property
    def online(self) -> bool:
        """Require a live state within 30 seconds and a connected broker."""
        return (
            not self._closed
            and self.broker_connected
            and self.last_seen is not None
            and self._clock() - self.last_seen < STALE_SECONDS
        )

    @property
    def ready(self) -> bool:
        """Control requires acknowledgement of the current room configuration."""
        return self.online and self.configured and not self.configuration_error

    def _fail_pending(self, reason: str) -> None:
        if self._pending:
            self.last_command_result = "RESULT_UNKNOWN"
        for future in self._pending.values():
            if not future.done():
                future.set_exception(GatewayError(reason))
        self._pending.clear()

    def _new_session(self) -> None:
        self._fail_pending("RESULT_UNKNOWN: session interrupted")
        self.session_id = uuid4().hex
        self._heartbeat_sequence = 0
        self._command_sequence = 0
        self._heartbeat_at = self._config_at = float("-inf")
        self.configured = False
        self.configuration_error = None
        # Prototype config_ack has no session_id; reserve a new revision so
        # delayed acknowledgements from the previous session cannot unlock it.
        self.revision += 1
        self.ready_event.clear()

    def connection_changed(self, connected: bool) -> None:
        """Invalidate old snapshots and session on broker reconnection."""
        if self._closed or connected == self.broker_connected:
            return
        self.broker_connected = connected
        self.last_seen = None
        self._new_session()
        self._changed()

    def set_room(self, room: str) -> None:
        """Synchronize HA's area name; never silently truncate Chinese text."""
        try:
            validate_room(room)
        except ValueError:
            self.configuration_error = "ROOM_TOO_LONG"
            self.configured = False
            self.ready_event.clear()
            self._fail_pending("RESULT_UNKNOWN: room configuration invalid")
            self._changed()
            return
        if room == self.room and self.configuration_error != "ROOM_TOO_LONG":
            return
        self.room = room
        self.configuration_error = None
        self.revision = max(self.revision, self.state.get("config_revision", 0)) + 1
        self.configured = False
        self.ready_event.clear()
        self._config_at = float("-inf")
        self._fail_pending("RESULT_UNKNOWN: room configuration changed")
        self._changed()

    def _envelope(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "gateway_id": self.gateway_id,
            "boot_id": self.boot_id,
            "controller_id": self.controller_id,
            "binding_token": self._token,
            "session_id": self.session_id,
        }

    def feed(self, suffix: str, payload: str, retained: bool) -> bool:
        """Validate incoming data. Return True when a live report can start sync."""
        if self._closed:
            return False
        if suffix == "availability":
            if payload == "offline":
                self.last_seen = None
                self._new_session()
                self._changed()
            return False
        if retained or not self.broker_connected or len(payload.encode("utf-8")) > 2048:
            return False
        try:
            data = json.loads(payload)
        except (ValueError, RecursionError):
            return False
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            return False
        if data.get("gateway_id") != self.gateway_id:
            return False
        boot = data.get("boot_id")
        seq = data.get("sequence")
        if not isinstance(boot, str) or not re.fullmatch(r"[0-9a-f]{16}", boot):
            return False
        if not uint32(seq) or not seq:
            return False
        if suffix in ("hello", "state"):
            if not self._valid_state(data):
                return False
            if boot != self.boot_id:
                self.boot_id = boot
                self.last_sequence = -1
                self.revision = data["config_revision"] + 1
                self._new_session()
            if seq <= self.last_sequence:
                return False
            # A stale node may have lost its session: perform a new handshake.
            if not self.online and self.last_seen is not None:
                self._new_session()
            self.last_sequence = seq
            self.state = {
                key: data[key]
                for key in (
                    "firmware",
                    "room",
                    "config_revision",
                    "controller_online",
                    "wifi_rssi",
                    "free_heap",
                    "min_free_heap",
                    "uptime_ms",
                    "reset_reason",
                    "indicator",
                    "transport",
                )
            }
            self.last_seen = self._clock()
            if self.revision <= data["config_revision"] and (
                not self.configured or data["room"] != self.room
            ):
                self.revision = data["config_revision"] + 1
                self.configured = False
                self.ready_event.clear()
                self._config_at = float("-inf")
            self._changed()
            return True
        if boot != self.boot_id or seq <= self.last_sequence or not self.online:
            return False
        if suffix == "config_ack":
            if not uint32(data.get("config_revision")) or data["config_revision"] != self.revision:
                return False
            error = data.get("error_code")
            if not isinstance(error, str) or len(error) > 64:
                return False
            self.last_sequence = seq
            self.configuration_error = error or None
            self.configured = not error
            if self.ready:
                self.ready_event.set()
            else:
                self.ready_event.clear()
            self._changed()
        elif suffix == "ir":
            raw = data.get("raw")
            frequency = data.get("frequency_khz")
            if (
                not isinstance(raw, list)
                or not 2 <= len(raw) <= IR_MAX_RAW
                or not uint32(frequency)
                or not 30 <= frequency <= 60
                or any(not uint32(item) or not 100 <= item <= 30000 for item in raw)
            ):
                return False
            self.last_sequence = seq
            self.last_ir_capture = {
                "capture_id": data.get("capture_id"),
                "frequency_khz": frequency,
                "protocol": str(data.get("protocol", "UNKNOWN"))[:40],
                "bits": data.get("bits") if uint32(data.get("bits")) else 0,
                "raw": raw,
            }
            self._changed()
            return True
        elif suffix == "ack":
            if data.get("session_id") != self.session_id:
                return False
            command_id = data.get("command_id")
            if not isinstance(command_id, str) or command_id not in self._pending:
                return False
            result, error = data.get("result"), data.get("error_code")
            if result not in ("executed", "rejected") or not isinstance(error, str):
                return False
            confidence = data.get("confidence")
            if len(error) > 64 or data.get("indicator") not in COLORS or confidence not in (
                "output_level_only",
                "transmitted_only",
            ):
                return False
            self.last_sequence = seq
            future = self._pending.pop(command_id)
            self.last_command_result = result if not error else f"{result}:{error}"
            self.state["indicator"] = data["indicator"]
            if not future.done():
                future.set_result({"result": result, "error_code": error, "confidence": confidence})
            self._changed()
        return False

    @staticmethod
    def _valid_state(data: dict[str, Any]) -> bool:
        for key in ("config_revision", "free_heap", "min_free_heap", "uptime_ms", "reset_reason"):
            if not uint32(data.get(key)):
                return False
        return (
            isinstance(data.get("firmware"), str)
            and data["firmware"] in SUPPORTED_FIRMWARE
            and isinstance(data.get("room"), str)
            and len(data["room"].encode("utf-8")) <= 32
            and type(data.get("controller_online")) is bool
            and type(data.get("wifi_rssi")) is int
            and -127 <= data["wifi_rssi"] <= 0
            and data.get("indicator") in COLORS
            and data.get("transport") in ("tls", "lab_plain")
        )

    async def tick(self) -> None:
        """Send live controller heartbeats and retry only idempotent config."""
        async with self._lock:
            if not self.online or not self.boot_id:
                self.ready_event.clear()
                if self._pending:
                    self._fail_pending("RESULT_UNKNOWN: gateway unavailable")
                self._changed()
                return
            now = self._clock()
            if now - self._heartbeat_at >= HEARTBEAT_SECONDS:
                self._heartbeat_sequence += 1
                await self._publish(
                    "controller",
                    {
                        **self._envelope(),
                        "sequence": self._heartbeat_sequence,
                    },
                )
                self._heartbeat_at = now
            if not self.configured and self.configuration_error != "ROOM_TOO_LONG":
                if now - self._config_at >= 5:
                    if not 1 <= self.revision <= 0xFFFFFFFF:
                        self.configuration_error = "CONFIG_REVISION_EXHAUSTED"
                        self._changed()
                        return
                    await self._publish(
                        "config",
                        {
                            **self._envelope(),
                            "config_revision": self.revision,
                            "room": self.room,
                        },
                    )
                    self._config_at = now
            self._changed()

    async def command(
        self,
        action: str,
        color: str | None = None,
        raw: list[int] | None = None,
        frequency_khz: int = 38,
        ack_timeout: float = COMMAND_TIMEOUT,
    ) -> dict[str, Any]:
        """Send once and await device ACK; never replay an uncertain action."""
        if action == "set_indicator" and color in COLORS:
            target, parameters = "onboard.rgb", {"color": color}
        elif action == "request_diagnostics" and color is None:
            target, parameters = "gateway", {}
        elif action in ("receive_start", "receive_stop") and color is None and raw is None:
            target, parameters = "onboard.ir", {}
        elif action == "send_raw" and color is None and isinstance(raw, list):
            if not 2 <= len(raw) <= IR_MAX_RAW or not 30 <= frequency_khz <= 60:
                raise GatewayError("INVALID_ARGUMENT")
            if any(type(value) is not int or not 100 <= value <= 30000 for value in raw):
                raise GatewayError("INVALID_ARGUMENT")
            target, parameters = "onboard.ir", {"raw": raw, "frequency_khz": frequency_khz}
        else:
            raise GatewayError("UNSUPPORTED_CAPABILITY")
        command_id = uuid4().hex
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        async with self._lock:
            if not self.ready:
                raise GatewayError("GATEWAY_NOT_READY")
            if len(self._pending) >= MAX_PENDING:
                raise GatewayError("BUSY")
            self._command_sequence += 1
            if self._command_sequence > 0xFFFFFFFF:
                raise GatewayError("COMMAND_SEQUENCE_EXHAUSTED")
            self._pending[command_id] = future
            try:
                await self._publish(
                    "cmd",
                    {
                        **self._envelope(),
                        "command_id": command_id,
                        "command_seq": self._command_sequence,
                        "config_revision": self.revision,
                        "target": target,
                        "action": action,
                        "parameters": parameters,
                    },
                )
            except BaseException:
                self._pending.pop(command_id, None)
                future.cancel()
                self.last_command_result = "RESULT_UNKNOWN"
                self._changed()
                raise
        try:
            async with asyncio.timeout(ack_timeout):
                result = await future
        except TimeoutError as err:
            self.last_command_result = "RESULT_UNKNOWN"
            self._changed()
            raise GatewayError("RESULT_UNKNOWN: acknowledgement timeout") from err
        finally:
            self._pending.pop(command_id, None)
        if result["result"] != "executed" or result["error_code"]:
            raise GatewayError(result["error_code"] or "EXECUTION_REJECTED")
        self.last_command_result = result["confidence"]
        self._changed()
        return result

    def close(self) -> None:
        """Stop control and release waiters on unload."""
        self._closed = True
        self.last_seen = None
        self.configured = False
        self.ready_event.clear()
        self._fail_pending("RESULT_UNKNOWN: integration unloaded")
