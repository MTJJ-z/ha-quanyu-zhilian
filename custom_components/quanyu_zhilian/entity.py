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


class ComponentEntity(GatewayEntity):
    """Base for firmware-discovered, protocol-neutral entities."""

    _attr_entity_category = None

    def __init__(self, coordinator: GatewayCoordinator, descriptor: dict, key: str) -> None:
        super().__init__(coordinator, f"component_{key}")
        self._attr_translation_key = None
        self.component_id = descriptor["id"]
        self._component_platform = descriptor["platform"]
        self._attr_icon = descriptor.get("icon")
        category = descriptor.get("entity_category")
        self._attr_entity_category = EntityCategory(category) if category else None

    @property
    def descriptor(self) -> dict | None:
        return self.coordinator.protocol.components.get(self.component_id)

    @property
    def name(self) -> str | None:
        descriptor = self.descriptor
        return descriptor["name"] if descriptor else None

    @property
    def available(self) -> bool:
        descriptor = self.descriptor
        return (
            self.coordinator.protocol.ready
            and descriptor is not None
            and descriptor["platform"] == self._component_platform
        )

    @property
    def component_state(self) -> dict:
        descriptor = self.descriptor
        if descriptor is None:
            return {}
        return self.coordinator.protocol.component_states.get(descriptor["state_key"], {})

    @property
    def extra_state_attributes(self):
        return self.component_state.get("attributes")

    async def execute(self, command_id: str, parameters: dict | None = None) -> None:
        await self.coordinator.async_command(
            command_id,
            target=self.component_id,
            command_id=command_id,
            parameters=parameters or {},
        )
