"""Quanyu Zhilian managed CYD gateways."""

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from .const import CONF_AREA_ID, CONF_GATEWAY_ID, DOMAIN, IR_CAPTURE_EVENT
from .coordinator import GatewayCoordinator
from .protocol import GatewayError

PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT, Platform.BUTTON)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a gateway; offline devices can load and reconnect later."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("Configure and enable the MQTT integration first")
    coordinator = GatewayCoordinator(hass, dict(entry.data), entry)
    entry.runtime_data = coordinator
    coordinators = hass.data.setdefault(DOMAIN, {})
    coordinators[entry.data[CONF_GATEWAY_ID]] = coordinator
    if not hass.services.has_service(DOMAIN, "start_ir_capture"):
        async def get_gateway(call):
            gateway = hass.data.get(DOMAIN, {}).get(call.data.get("gateway_id"))
            if gateway is None:
                raise HomeAssistantError("Unknown CYD gateway_id")
            return gateway

        async def start_ir_capture(call):
            await (await get_gateway(call)).async_command("receive_start")

        async def stop_ir_capture(call):
            await (await get_gateway(call)).async_command("receive_stop")

        async def send_ir_raw(call):
            gateway = await get_gateway(call)
            await gateway.async_command(
                "send_raw",
                raw=call.data["raw"],
                frequency_khz=call.data.get("frequency_khz", 38),
            )

        hass.services.async_register(DOMAIN, "start_ir_capture", start_ir_capture)
        hass.services.async_register(DOMAIN, "stop_ir_capture", stop_ir_capture)
        hass.services.async_register(DOMAIN, "send_ir_raw", send_ir_raw)
    async def forward_ir_capture(data):
        hass.bus.async_fire(IR_CAPTURE_EVENT, {"gateway_id": entry.data[CONF_GATEWAY_ID], **data})

    coordinator.ir_capture_callback = forward_ir_capture
    registry = dr.async_get(hass)
    existing = registry.async_get_device(identifiers={(DOMAIN, entry.data[CONF_GATEWAY_ID])})
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_GATEWAY_ID])},
        manufacturer="全域智联",
        model="CYD ESP32-32E-1",
        name=f"CYD {entry.data[CONF_GATEWAY_ID]}",
    )
    coordinator.device_id = device.id
    # Only initialize the area on creation. Subsequent device-area edits in HA
    # are authoritative and must not be overwritten by a reload.
    if existing is None and (area_id := entry.data.get(CONF_AREA_ID)):
        if ar.async_get(hass).async_get_area(area_id):
            registry.async_update_device(device.id, area_id=area_id)
    try:
        await coordinator.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        coordinator.async_stop()
        raise
    entry.async_on_unload(coordinator.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entities, MQTT subscriptions, timer and pending commands."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.async_stop()
        hass.data.get(DOMAIN, {}).pop(entry.data[CONF_GATEWAY_ID], None)
        return True
    return False
