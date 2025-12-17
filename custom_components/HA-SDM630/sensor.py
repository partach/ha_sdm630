from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import CoordinatorEntity
from .const import DOMAIN, VALIDATED_REGISTER_MAP as REGISTER_MAP
from .coordinator import SDM630Coordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: SDM630Coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for key, info in REGISTER_MAP.items():
        entities.append(
            SDM630Sensor(
                coordinator=coordinator,
                entry=entry,
                key=key,
                info=info,
            )
        )

    async_add_entities(entities)


class SDM630Sensor(CoordinatorEntity, SensorEntity):  # ← Inherit from CoordinatorEntity
    """Representation of an SDM630 sensor."""

    def __init__(self, coordinator: SDM630Coordinator, entry: ConfigEntry, key: str, info: dict):
        """Initialize the sensor."""
        super().__init__(coordinator)  # This handles update listening
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"{entry.title} {info['name']}"
        self._attr_native_unit_of_measurement = info.get("unit")
        self._attr_device_class = info.get("device_class")
        self._attr_state_class = info.get("state_class")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get(self._key)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data.get(self._key) is not None
