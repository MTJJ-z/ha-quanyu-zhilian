"""Connect the CYD protocol state machine to Home Assistant MQTT."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import CONF_BINDING_TOKEN, CONF_CONTROLLER_ID, CONF_GATEWAY_ID, DOMAIN, TOPIC_ROOT
from .protocol import GatewayError, GatewayProtocol

_LOGGER = logging.getLogger(__name__)


class GatewayCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Maintain one gateway without opening a second MQTT connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        data: dict[str, Any],
        entry: ConfigEntry | None = None,
        probe_room: str = "Unassigned",
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry)
        self.entry = entry
        self.device_id: str | None = None
        self._probe_room = probe_room
        self._unsubscribers: list[Any] = []
        self.last_report_at: datetime | None = None
        self.ir_capture_callback = None
        self._stopped = False
        self.protocol = GatewayProtocol(
            data[CONF_GATEWAY_ID],
            data[CONF_CONTROLLER_ID],
            data[CONF_BINDING_TOKEN],
            self._publish,
            self._notify,
        )
        self.prefix = f"{TOPIC_ROOT}/{self.protocol.gateway_id}/"
        self.async_set_updated_data({})

    def _room(self) -> str:
        if self.device_id is None:
            return self._probe_room
        device = dr.async_get(self.hass).async_get(self.device_id)
        area = (
            ar.async_get(self.hass).async_get_area(device.area_id)
            if device and device.area_id
            else None
        )
        return area.name if area else "Unassigned"

    @callback
    def _notify(self) -> None:
        if not self._stopped:
            self.async_set_updated_data(
                {
                    **self.protocol.state,
                    "online": self.protocol.online,
                    "ready": self.protocol.ready,
                    "configuration_error": self.protocol.configuration_error,
                    "last_command_result": self.protocol.last_command_result,
                }
            )

    async def _publish(self, suffix: str, payload: dict[str, Any]) -> None:
        if self._stopped or not mqtt.is_connected(self.hass):
            raise GatewayError("BROKER_UNAVAILABLE")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 2048:
            raise GatewayError("MESSAGE_TOO_LARGE")
        # The prototype firmware does not enforce an absolute command deadline;
        # only use it for isolated onboard-indicator tests.
        try:
            async with asyncio.timeout(5):
                await mqtt.async_publish(
                    self.hass,
                    self.prefix + suffix,
                    encoded,
                    qos=1,
                    retain=False,
                )
        except (TimeoutError, HomeAssistantError) as err:
            raise GatewayError("RESULT_UNKNOWN: MQTT publication failed") from err

    async def _receive(self, message: mqtt.ReceiveMessage) -> None:
        if self._stopped or not isinstance(message.payload, str):
            return
        live = self.protocol.feed(
            message.topic.removeprefix(self.prefix),
            message.payload,
            message.retain,
        )
        if message.topic.endswith("/ir") and self.protocol.last_ir_capture and self.ir_capture_callback:
            self.ir_capture_callback(self.protocol.last_ir_capture)
        if live:
            self.last_report_at = dt_util.utcnow()
            if self.device_id and self.entry:
                dr.async_get(self.hass).async_update_device(
                    self.device_id,
                    sw_version=self.protocol.state["firmware"],
                )
            await self._tick()

    async def _tick(self, now: datetime | None = None) -> None:
        if self._stopped:
            return
        self.protocol.connection_changed(mqtt.is_connected(self.hass))
        self.protocol.set_room(self._room())
        try:
            await self.protocol.tick()
        except (HomeAssistantError, GatewayError):
            # Never log payloads or broker exceptions that may include secrets.
            _LOGGER.warning("CYD controller synchronization could not be published")
            self.protocol.connection_changed(False)

    @callback
    def _connection_changed(self, connected: bool) -> None:
        self.protocol.connection_changed(connected)

    async def async_start(self) -> None:
        try:
            self.protocol.set_room(self._room())
            self.protocol.connection_changed(mqtt.is_connected(self.hass))
            self._unsubscribers.append(
                mqtt.async_subscribe_connection_status(
                    self.hass,
                    self._connection_changed,
                )
            )
            for suffix in ("hello", "state", "ack", "config_ack", "availability"):
                self._unsubscribers.append(
                    await mqtt.async_subscribe(
                        self.hass,
                        self.prefix + suffix,
                        self._receive,
                        qos=1,
                    )
                )
            self._unsubscribers.append(
                async_track_time_interval(
                    self.hass,
                    self._tick,
                    timedelta(seconds=5),
                )
            )
        except BaseException:
            self.async_stop()
            raise

    @callback
    def async_stop(self) -> None:
        self._stopped = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self.protocol.close()

    async def async_command(
        self,
        action: str,
        color: str | None = None,
        raw: list[int] | None = None,
        frequency_khz: int = 38,
    ) -> dict[str, Any]:
        try:
            return await self.protocol.command(action, color, raw, frequency_khz)
        except GatewayError as err:
            raise HomeAssistantError(str(err)) from err
