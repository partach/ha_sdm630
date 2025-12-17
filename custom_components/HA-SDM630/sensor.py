"""Sensor platform for SDM630."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import async_get_current_platform

from .const import DOMAIN, REGISTER_MAP
from .coordinator import SDM630Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Set up sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for key, info in REGISTER_MAP.items():
        entities.append(SDM630Sensor(coordinator, entry, key, info))

    async_add_entities(entities)


class SDM630Sensor(SensorEntity):
    """SDM630 sensor entity."""

    def __init__(self, coordinator: SDM630Coordinator, entry: ConfigEntry, key: str, info: dict):
        super().__init__(coordinator=coordinator)
        self._key = key
        self._attr_name = f"{entry.data[CONF_NAME]} {info['name']}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = info.get("unit")
        self._attr_device_class = info.get("device_class")
        self._attr_state_class = "measurement"  # Or "total_increasing" for energy

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get(self._key)
