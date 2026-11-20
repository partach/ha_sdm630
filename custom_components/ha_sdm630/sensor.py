"""Sensor platform for SDM630."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SDM630ConfigEntry
from .const import DOMAIN
from .coordinator import HA_SDM630Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SDM630ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one sensor per register in the selected register set."""
    coordinator = entry.runtime_data
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or "SDM630",
        manufacturer="Eastron",
        model="SDM630",
        configuration_url=f"homeassistant://config/integrations/integration/{entry.entry_id}",
    )

    # Drop sensors left over from a larger register set (e.g. Full -> Basic)
    wanted = {_unique_id(entry.entry_id, key) for key in coordinator.register_map}
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain == "sensor" and reg_entry.unique_id not in wanted:
            _LOGGER.debug("Removing %s: not in the selected register set", reg_entry.entity_id)
            registry.async_remove(reg_entry.entity_id)

    async_add_entities(
        HA_SDM630Sensor(coordinator, entry.entry_id, key, info, device_info)
        for key, info in coordinator.register_map.items()
    )


def _unique_id(entry_id: str, key: str) -> str:
    return f"{entry_id}_{key}"


class HA_SDM630Sensor(CoordinatorEntity[HA_SDM630Coordinator], SensorEntity):
    """Representation of an SDM630 sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HA_SDM630Coordinator,
        entry_id: str,
        key: str,
        info: dict,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = _unique_id(entry_id, key)
        self._attr_name = info["name"]
        self._attr_device_info = device_info
        self._attr_native_unit_of_measurement = info.get("unit")
        self._attr_device_class = info.get("device_class")
        self._attr_state_class = info.get("state_class")
        self._attr_suggested_display_precision = info.get("precision")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return (self.coordinator.data or {}).get(self._key)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None
