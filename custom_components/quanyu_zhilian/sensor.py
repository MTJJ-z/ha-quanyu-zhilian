"""Health sensors for CYD; none represent external room equipment."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import GatewayEntity

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    SensorEntityDescription(
        key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="free_heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="min_free_heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(key="firmware"),
    SensorEntityDescription(key="reset_reason"),
    SensorEntityDescription(key="transport"),
    SensorEntityDescription(key="last_report", device_class=SensorDeviceClass.TIMESTAMP),
    SensorEntityDescription(key="last_command_result"),
    SensorEntityDescription(key="configuration_status"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            *(GatewaySensor(entry.runtime_data, description) for description in DESCRIPTIONS),
            GatewayIrCaptureSensor(entry.runtime_data),
        ]
    )


class GatewaySensor(GatewayEntity, SensorEntity):
    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        # Preserve last communication/result for diagnosing an offline gateway.
        if self.entity_description.key in (
            "last_report",
            "last_command_result",
            "configuration_status",
        ):
            return not self.coordinator._stopped
        return super().available

    @property
    def native_value(self):
        key = self.entity_description.key
        protocol = self.coordinator.protocol
        if key == "uptime":
            value = protocol.state.get("uptime_ms")
            return value / 1000 if value is not None else None
        if key == "last_report":
            return self.coordinator.last_report_at
        if key == "last_command_result":
            return protocol.last_command_result
        if key == "configuration_status":
            return protocol.configuration_error or ("ready" if protocol.ready else "waiting")
        return protocol.state.get(key)


class GatewayIrCaptureSensor(GatewayEntity, SensorEntity):
    """Expose the most recently learned IR signal for scripts and automations."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_ir_capture")

    @property
    def native_value(self):
        capture = self.coordinator.protocol.last_ir_capture
        return capture.get("protocol") if capture else None

    @property
    def extra_state_attributes(self):
        capture = self.coordinator.protocol.last_ir_capture
        if not capture:
            return None
        return {
            "capture_id": capture["capture_id"],
            "bits": capture["bits"],
            "frequency_khz": capture["frequency_khz"],
            "raw": capture["raw"],
        }
