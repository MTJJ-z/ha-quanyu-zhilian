"""HA actions for the bundled offline infrared library."""

import sqlite3

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .ir_library import InfraredLibrary, LibraryError, raw_parameters


def register_ir_services(hass: HomeAssistant) -> None:
    """Register once, independent of any particular gateway's lifetime."""
    if hass.services.has_service(DOMAIN, "ir_search"):
        return
    library = InfraredLibrary()

    async def worker(method, *args):
        try:
            return await hass.async_add_executor_job(method, *args)
        except (LibraryError, sqlite3.Error, OSError) as err:
            raise HomeAssistantError(f"Local infrared library: {err}") from err

    async def search(call: ServiceCall):
        return await worker(library.search, call.data.get("query", ""),
                            call.data.get("category", ""), call.data.get("limit", 20),
                            call.data.get("offset", 0))

    async def inspect(call: ServiceCall):
        return await worker(library.profile, call.data["profile_id"])

    async def send(call: ServiceCall):
        signal = await worker(library.signal, call.data["profile_id"], call.data["signal_index"])
        try:
            parameters = raw_parameters(signal)
        except LibraryError as err:
            raise HomeAssistantError(str(err)) from err
        gateway = hass.data.get(DOMAIN, {}).get(call.data["gateway_id"])
        if gateway is None:
            raise HomeAssistantError("Unknown gateway_id")
        # Use discovery rather than assuming a target ID from one firmware.
        candidates = [(descriptor["id"], command["id"])
                      for descriptor in gateway.protocol.components.values()
                      for command in descriptor["commands"].values()
                      if command["action"] == "ir.send_raw"]
        if len(candidates) != 1:
            raise HomeAssistantError("Gateway must advertise exactly one ir.send_raw command")
        target, command_id = candidates[0]
        await gateway.async_command(command_id, target=target, command_id=command_id,
                                    parameters=parameters)

    async def gateways(call: ServiceCall):
        return {"gateways": [
            {"gateway_id": gateway_id, "online": gateway.protocol.online,
             "ready": gateway.protocol.ready,
             "room": gateway.protocol.room,
             "ir_send": any(command["action"] == "ir.send_raw"
                             for descriptor in gateway.protocol.components.values()
                             for command in descriptor["commands"].values())}
            for gateway_id, gateway in hass.data.get(DOMAIN, {}).items()
        ]}

    profile_schema = {vol.Required("profile_id"): cv.string}
    hass.services.async_register(
        DOMAIN, "ir_search", search,
        schema=vol.Schema({vol.Optional("query", default=""): cv.string,
                           vol.Optional("category", default=""): cv.string,
                           vol.Optional("limit", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                           vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0))}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, "ir_inspect", inspect,
                                 schema=vol.Schema(profile_schema),
                                 supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "ir_gateways", gateways,
                                 schema=vol.Schema({}),
                                 supports_response=SupportsResponse.ONLY)
    hass.services.async_register(
        DOMAIN, "ir_send", send,
        schema=vol.Schema({**profile_schema, vol.Required("gateway_id"): cv.string,
                           vol.Required("signal_index"): vol.All(vol.Coerce(int), vol.Range(min=0))}),
    )
