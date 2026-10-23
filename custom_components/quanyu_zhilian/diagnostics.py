"""Diagnostics without secrets or raw received payloads."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_AREA_ID, CONF_BINDING_TOKEN, CONF_CONTROLLER_ID, CONF_GATEWAY_ID


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    protocol = coordinator.protocol
    return async_redact_data(
        {
            "config": dict(entry.data),
            "protocol": "qyzl.cyd.prototype/1",
            "online": protocol.online,
            "control_ready": protocol.ready,
            "configuration_error": protocol.configuration_error,
            "last_command_result": protocol.last_command_result,
            "telemetry": {key: value for key, value in protocol.state.items() if key != "room"},
        },
        {CONF_BINDING_TOKEN, CONF_GATEWAY_ID, CONF_CONTROLLER_ID, CONF_AREA_ID},
    )
