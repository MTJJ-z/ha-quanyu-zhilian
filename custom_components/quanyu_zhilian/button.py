"""Explicitly request current CYD diagnostics."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ComponentEntity, GatewayEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            GatewayDiagnosticsButton(entry.runtime_data, "request_diagnostics"),
        ]
    )
    entry.runtime_data.register_component_platform(
        "button",
        async_add_entities,
        lambda descriptor: [
            GatewayComponentButton(entry.runtime_data, descriptor, command)
            for command in descriptor["commands"].values()
            if not any(
                parameter.get("required", True)
                for parameter in command["parameters"].values()
            )
        ],
    )


class GatewayDiagnosticsButton(GatewayEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        return self.coordinator.protocol.ready

    async def async_press(self) -> None:
        await self.coordinator.async_command("request_diagnostics")


class GatewayComponentButton(ComponentEntity, ButtonEntity):
    def __init__(self, coordinator, descriptor: dict, command: dict) -> None:
        super().__init__(coordinator, descriptor, f"{descriptor['id']}_{command['id']}")
        self._command_id = command["id"]

    @property
    def name(self) -> str | None:
        descriptor = self.descriptor
        command = descriptor["commands"].get(self._command_id) if descriptor else None
        return f"{descriptor['name']} {command['name']}" if descriptor and command else None

    @property
    def available(self) -> bool:
        return super().available

    async def async_press(self) -> None:
        await self.execute(self._command_id)
