"""Transport-independent state machine for the existing CYD firmware.

MQTT ACLs are the trust boundary: telemetry is not cryptographically signed.
Retained telemetry is deliberately ignored until a live report arrives.
"""

import asyncio
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from .const import (
    COLORS,
    COMMAND_TIMEOUT,
    HEARTBEAT_SECONDS,
    MAX_PENDING,
    SCHEMA,
    STALE_SECONDS,
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


def reject_json_constant(value: str) -> None:
    """Python's JSON decoder accepts NaN and Infinity unless explicitly rejected."""
    raise ValueError(f"Invalid JSON constant: {value}")


COMPONENT_ID = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
COMPONENT_PLATFORMS = {"sensor", "binary_sensor", "switch", "select", "button"}
PARAMETER_TYPES = {"string", "boolean", "integer", "number", "integer_array"}


def validate_components(model: Any, raw: Any) -> dict[str, dict[str, Any]] | None:
    """Validate the optional, versioned component discovery extension."""
    if model is None and raw is None:
        return {}
    if type(model) is not int or model != 1 or not isinstance(raw, list) or len(raw) > 64:
        return None
    components: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            return None
        component_id = item.get("id")
        platform = item.get("platform")
        name = item.get("name")
        state_key = item.get("state_key")
        commands = item.get("commands")
        if (
            not isinstance(component_id, str)
            or not COMPONENT_ID.fullmatch(component_id)
            or component_id in components
            or not isinstance(platform, str)
            or platform not in COMPONENT_PLATFORMS
            or not isinstance(name, str)
            or not 1 <= len(name) <= 64
            or not isinstance(state_key, str)
            or not COMPONENT_ID.fullmatch(state_key)
            or not isinstance(commands, list)
            or len(commands) > 16
        ):
            return None
        if any(existing["state_key"] == state_key for existing in components.values()):
            return None
        normalized_commands: dict[str, dict[str, Any]] = {}
        for command in commands:
            if not isinstance(command, dict):
                return None
            command_id, action = command.get("id"), command.get("action")
            command_name, params = command.get("name"), command.get("parameters")
            if (
                not isinstance(command_id, str)
                or not COMPONENT_ID.fullmatch(command_id)
                or command_id in normalized_commands
                or not isinstance(action, str)
                or not COMPONENT_ID.fullmatch(action)
                or not isinstance(command_name, str)
                or not 1 <= len(command_name) <= 64
                or not isinstance(params, list)
                or len(params) > 16
            ):
                return None
            normalized_params: dict[str, dict[str, Any]] = {}
            for parameter in params:
                if not isinstance(parameter, dict):
                    return None
                param_name, param_type = parameter.get("name"), parameter.get("type")
                required = parameter.get("required", True)
                if (
                    not isinstance(param_name, str)
                    or not COMPONENT_ID.fullmatch(param_name)
                    or param_name in normalized_params
                    or not isinstance(param_type, str)
                    or param_type not in PARAMETER_TYPES
                    or type(required) is not bool
                ):
                    return None
                for bound in ("min", "max"):
                    if bound in parameter and (
                        type(parameter[bound]) not in (int, float)
                        or not math.isfinite(parameter[bound])
                    ):
                        return None
                for bound in ("min_items", "max_items"):
                    if bound in parameter and type(parameter[bound]) is not int:
                        return None
                if (
                    "min" in parameter
                    and "max" in parameter
                    and parameter["min"] > parameter["max"]
                ) or (
                    "min_items" in parameter
                    and "max_items" in parameter
                    and parameter["min_items"] > parameter["max_items"]
                ):
                    return None
                normalized_params[param_name] = dict(parameter)
            normalized_commands[command_id] = {
                "id": command_id,
                "action": action,
                "name": command_name,
                "parameters": normalized_params,
            }
        descriptor = dict(item)
        descriptor["commands"] = normalized_commands
        for field in ("icon", "device_class", "unit", "state_class", "entity_category"):
            if field in descriptor and (
                not isinstance(descriptor[field], str) or len(descriptor[field]) > 64
            ):
                return None
        if descriptor.get("entity_category") not in (None, "config", "diagnostic"):
            return None
        if descriptor.get("state_class") not in (
            None,
            "measurement",
            "total",
            "total_increasing",
        ):
            return None
        if platform in ("switch", "select"):
            control = item.get("control")
            if (
                not isinstance(control, dict)
                or not isinstance(control.get("command_id"), str)
                or not isinstance(control.get("value_parameter"), str)
            ):
                return None
            command = normalized_commands.get(control.get("command_id"))
            value_parameter = control.get("value_parameter")
            parameter = command and command["parameters"].get(value_parameter)
            expected = "boolean" if platform == "switch" else "string"
            if not parameter or parameter["type"] != expected or not parameter.get("required", True):
                return None
            if platform == "select":
                options = item.get("options")
                if (
                    not isinstance(options, list)
                    or not 1 <= len(options) <= 64
                    or any(not isinstance(option, str) or len(option) > 64 for option in options)
                    or len(set(options)) != len(options)
                ):
                    return None
        components[component_id] = descriptor
    return components


def validate_parameters(command: dict[str, Any], values: Any) -> dict[str, Any]:
    """Validate execute-service arguments against an advertised command."""
    if not isinstance(values, dict):
        raise GatewayError("INVALID_ARGUMENT")
    schema = command["parameters"]
    if values.keys() - schema.keys():
        raise GatewayError("INVALID_ARGUMENT")
    result: dict[str, Any] = {}
    for name, descriptor in schema.items():
        if name not in values:
            if descriptor.get("required", True):
                raise GatewayError("INVALID_ARGUMENT")
            continue
        value, kind = values[name], descriptor["type"]
        valid = (
            isinstance(value, str) if kind == "string" else
            type(value) is bool if kind == "boolean" else
            type(value) is int if kind == "integer" else
            type(value) in (int, float) and not isinstance(value, bool) if kind == "number" else
            isinstance(value, list) and all(type(v) is int for v in value) if kind == "integer_array" else
            False
        )
        if not valid:
            raise GatewayError("INVALID_ARGUMENT")
        if kind in ("integer", "number"):
            if kind == "number" and not math.isfinite(value):
                raise GatewayError("INVALID_ARGUMENT")
            if "min" in descriptor and value < descriptor["min"]:
                raise GatewayError("INVALID_ARGUMENT")
            if "max" in descriptor and value > descriptor["max"]:
                raise GatewayError("INVALID_ARGUMENT")
        if kind == "integer_array":
            if len(value) < descriptor.get("min_items", 0):
                raise GatewayError("INVALID_ARGUMENT")
            if len(value) > descriptor.get("max_items", 1024):
                raise GatewayError("INVALID_ARGUMENT")
        result[name] = value
    return result


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
        self.components: dict[str, dict[str, Any]] = {}
        self.component_states: dict[str, dict[str, Any]] = {}
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
        if retained or not self.broker_connected or len(payload.encode("utf-8")) > 65536:
            return False
        try:
            data = json.loads(payload, parse_constant=reject_json_constant)
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
            if suffix == "hello" or "component_model" in data:
                components = validate_components(
                    data.get("component_model"), data.get("components")
                )
                if components is None:
                    return False
            else:
                components = self.components
            states = data.get("component_states", {})
            if not isinstance(states, dict) or len(states) > 64:
                return False
            normalized_states: dict[str, dict[str, Any]] = {}
            for component_id, component_state in states.items():
                descriptor = next(
                    (item for item in components.values() if item["state_key"] == component_id),
                    None,
                )
                if (
                    not descriptor
                    or not isinstance(component_state, dict)
                    or "value" not in component_state
                    or len(json.dumps(component_state, separators=(",", ":")).encode()) > 8192
                ):
                    return False
                value = component_state["value"]
                platform = descriptor["platform"]
                if platform in ("binary_sensor", "switch") and type(value) is not bool:
                    return False
                if platform == "sensor" and (
                    value is not None
                    and type(value) not in (str, int, float)
                ):
                    return False
                if platform == "sensor" and isinstance(value, str) and len(value) > 255:
                    return False
                if platform == "sensor" and type(value) is float and not math.isfinite(value):
                    return False
                if platform == "select" and (
                    not isinstance(value, str) or value not in descriptor["options"]
                ):
                    return False
                attributes = component_state.get("attributes", {})
                if not isinstance(attributes, dict):
                    return False
                normalized_states[component_id] = {"value": value, "attributes": attributes}
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
            if suffix == "hello" or "component_model" in data:
                self.components = components
            self.component_states = normalized_states
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
        if suffix == "ack":
            if data.get("session_id") != self.session_id:
                return False
            command_id = data.get("command_id")
            if not isinstance(command_id, str) or command_id not in self._pending:
                return False
            result, error = data.get("result"), data.get("error_code")
            if result not in ("executed", "rejected") or not isinstance(error, str):
                return False
            confidence = data.get("confidence")
            if (
                len(error) > 64
                or data.get("indicator") not in COLORS
                or not isinstance(confidence, str)
                or not 1 <= len(confidence) <= 64
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
            and 1 <= len(data["firmware"]) <= 32
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
        target: str | None = None,
        parameters: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        """Send once and await device ACK; never replay an uncertain action."""
        target_name = target
        wire_action = action
        if target is not None:
            if not COMPONENT_ID.fullmatch(target) or target not in self.components:
                raise GatewayError("UNKNOWN_COMPONENT")
            command = self.components[target]["commands"].get(command_id or action)
            if not command:
                raise GatewayError("UNKNOWN_COMMAND")
            parameters = validate_parameters(
                command, parameters if parameters is not None else {}
            )
            wire_action = command["action"]
        elif action == "set_indicator" and color in COLORS:
            target, parameters = "onboard.rgb", {"color": color}
        elif action == "request_diagnostics" and color is None:
            target, parameters = "gateway", {}
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
                        "target": target_name if target_name else target,
                        "action": wire_action,
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
