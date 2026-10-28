"""Explicitly request current CYD diagnostics."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import GatewayEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            GatewayDiagnosticsButton(entry.runtime_data, "request_diagnostics"),
            GatewayIrButton(entry.runtime_data, "start_ir_capture", "receive_start"),
            GatewayIrButton(entry.runtime_data, "stop_ir_capture", "receive_stop"),
        ]
    )


class GatewayDiagnosticsButton(GatewayEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        return self.coordinator.protocol.ready

    async def async_press(self) -> None:
        await self.coordinator.async_command("request_diagnostics")


class GatewayIrButton(GatewayEntity, ButtonEntity):
    def __init__(self, coordinator, key: str, action: str) -> None:
        super().__init__(coordinator, key)
        self._action = action

    @property
    def available(self) -> bool:
        return self.coordinator.protocol.ready

    async def async_press(self) -> None:
        await self.coordinator.async_command(self._action)
