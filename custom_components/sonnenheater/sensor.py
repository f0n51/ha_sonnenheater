"""Sensor platform for Sonnen Heater integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class SonnenSensorEntityDescription(SensorEntityDescription):
    """Extended entity description with JSON path and value type hint."""

    # Keys to traverse in the scraped JSON dict, e.g. ("sonnen_heater", "power")
    data_path: tuple[str, ...]
    # True  → strip trailing unit string ("2000 W" → 2000.0)
    # False → return value as-is (text or plain number)
    parse_numeric: bool = True


SENSORS: tuple[SonnenSensorEntityDescription, ...] = (
    SonnenSensorEntityDescription(
        key="heater_power",
        name="Heater Power",
        data_path=("sonnen_heater", "power"),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SonnenSensorEntityDescription(
        key="heater_water_temp",
        name="Heater Water Temperature",
        data_path=("sonnen_heater", "water_temperature"),
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    SonnenSensorEntityDescription(
        key="heater_max_temp",
        name="Heater Max Temperature",
        data_path=("sonnen_heater", "max_temperature"),
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    SonnenSensorEntityDescription(
        key="heater_state",
        name="Heater State",
        data_path=("sonnen_heater", "state"),
        parse_numeric=False,
    ),
)


def _dig(data: dict, path: tuple[str, ...]) -> Any:
    """Return nested dict value by key path, or None if any key is missing."""
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _to_float(value: Any) -> float | None:
    """Parse numeric value from int/float or a string like '2000 W' / '55 °C'."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.split()[0])
        except (ValueError, IndexError):
            return None
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sonnen Heater sensor entities."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SonnenSensor(coordinator, description) for description in SENSORS
    )


class SonnenSensor(CoordinatorEntity, SensorEntity):
    """A single sensor entity backed by the polling coordinator."""

    entity_description: SonnenSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: SonnenSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        info = (self.coordinator.data or {}).get("battery_info", {})
        return DeviceInfo(
            identifiers={(DOMAIN, DOMAIN)},
            name="Sonnen Heater",
            manufacturer="sonnen",
            model=info.get("model", "sonnenHeater"),
            serial_number=info.get("serial_number"),
            hw_version=info.get("capacity"),
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        raw = _dig(self.coordinator.data, self.entity_description.data_path)
        if raw is None:
            return None
        if self.entity_description.parse_numeric:
            return _to_float(raw)
        return raw
