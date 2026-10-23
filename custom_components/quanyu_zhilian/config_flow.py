"""Manually bind a preprovisioned CYD to Home Assistant."""

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import selector

from .const import (
    CONF_AREA_ID,
    CONF_BINDING_TOKEN,
    CONF_CONTROLLER_ID,
    CONF_GATEWAY_ID,
    DOMAIN,
    PROBE_TIMEOUT,
)
from .coordinator import GatewayCoordinator
from .protocol import GatewayError, validate_identity, validate_room


class QuanyuZhilianConfigFlow(ConfigFlow, domain=DOMAIN):
    """One config entry per stable gateway ID."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            try:
                validate_identity(
                    data[CONF_GATEWAY_ID],
                    data[CONF_CONTROLLER_ID],
                    data[CONF_BINDING_TOKEN],
                )
                await self.async_set_unique_id(data[CONF_GATEWAY_ID])
                self._abort_if_unique_id_configured()
                area_id = data.get(CONF_AREA_ID)
                area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
                if area_id and not area:
                    raise ValueError("invalid_area")
                room = area.name if area else "Unassigned"
                validate_room(room)
                if not await mqtt.async_wait_for_mqtt_client(self.hass):
                    errors["base"] = "mqtt_unavailable"
                else:
                    probe = GatewayCoordinator(self.hass, data, probe_room=room)
                    try:
                        await probe.async_start()
                        async with asyncio.timeout(PROBE_TIMEOUT):
                            await probe.protocol.ready_event.wait()
                        if not probe.protocol.ready:
                            raise GatewayError("Gateway not ready")
                    finally:
                        probe.async_stop()
                    return self.async_create_entry(title=f"CYD {data[CONF_GATEWAY_ID]}", data=data)
            except ValueError as err:
                errors["base"] = str(err)
            except (TimeoutError, HomeAssistantError, GatewayError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GATEWAY_ID): str,
                    vol.Required(CONF_CONTROLLER_ID): str,
                    vol.Required(CONF_BINDING_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
                    ),
                    vol.Optional(CONF_AREA_ID): selector.AreaSelector(),
                }
            ),
        )
