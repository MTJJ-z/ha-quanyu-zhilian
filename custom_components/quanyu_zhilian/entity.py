"""Shared gateway device and availability metadata."""

from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GatewayCoordinator


class GatewayEntity(CoordinatorEntity[GatewayCoordinator]):
    """Entity backed by current live gateway telemetry."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GatewayCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.protocol.gateway_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.protocol.gateway_id)},
        )

    @property
    def available(self) -> bool:
        return self.coordinator.protocol.online
