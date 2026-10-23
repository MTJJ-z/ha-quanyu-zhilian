"""Separate live connectivity from controller configuration readiness."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import GatewayEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        GatewayBinarySensor(entry.runtime_data, key) for key in ("gateway_online", "control_ready")
    )


class GatewayBinarySensor(GatewayEntity, BinarySensorEntity):
    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.key = key
        if key == "gateway_online":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def available(self) -> bool:
        return not self.coordinator._stopped

    @property
    def is_on(self) -> bool:
        return (
            self.coordinator.protocol.online
            if self.key == "gateway_online"
            else self.coordinator.protocol.ready
        )
