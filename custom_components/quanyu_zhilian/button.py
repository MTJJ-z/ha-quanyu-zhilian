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
    async_add_entities([GatewayDiagnosticsButton(entry.runtime_data, "request_diagnostics")])


class GatewayDiagnosticsButton(GatewayEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        return self.coordinator.protocol.ready

    async def async_press(self) -> None:
        await self.coordinator.async_command("request_diagnostics")
