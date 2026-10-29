"""Laboratory onboard RGB control with execution ACKs."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COLORS
from .entity import ComponentEntity, GatewayEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([GatewayIndicator(entry.runtime_data, "indicator")])
    entry.runtime_data.register_component_platform(
        "select",
        async_add_entities,
        lambda descriptor: [GatewayComponentSelect(entry.runtime_data, descriptor)],
    )


class GatewayIndicator(GatewayEntity, SelectEntity):
    _attr_options = list(COLORS)
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return self.coordinator.protocol.ready

    @property
    def current_option(self) -> str | None:
        return self.coordinator.protocol.state.get("indicator")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"state_confidence": "output_level_only"}

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_command("set_indicator", option)


class GatewayComponentSelect(ComponentEntity, SelectEntity):
    def __init__(self, coordinator, descriptor: dict) -> None:
        super().__init__(coordinator, descriptor, descriptor["id"])

    @property
    def options(self) -> list[str]:
        descriptor = self.descriptor
        return descriptor["options"] if descriptor else []

    @property
    def current_option(self) -> str | None:
        return self.component_state.get("value")

    @property
    def available(self) -> bool:
        return super().available

    async def async_select_option(self, option: str) -> None:
        control = self.descriptor["control"]
        command = self.descriptor["commands"][control["command_id"]]
        await self.execute(command["id"], {control["value_parameter"]: option})
