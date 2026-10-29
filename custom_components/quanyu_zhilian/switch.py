"""Switches dynamically described by CYD firmware."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ComponentEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry.runtime_data.register_component_platform(
        "switch",
        async_add_entities,
        lambda descriptor: [GatewayComponentSwitch(entry.runtime_data, descriptor)],
    )


class GatewayComponentSwitch(ComponentEntity, SwitchEntity):
    def __init__(self, coordinator, descriptor: dict) -> None:
        super().__init__(coordinator, descriptor, descriptor["id"])

    @property
    def is_on(self) -> bool | None:
        value = self.component_state.get("value")
        return value if type(value) is bool else None

    @property
    def available(self) -> bool:
        return super().available

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)

    async def _set(self, value: bool) -> None:
        control = self.descriptor["control"]
        command = self.descriptor["commands"][control["command_id"]]
        await self.execute(command["id"], {control["value_parameter"]: value})
