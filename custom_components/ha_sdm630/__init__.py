"""The SDM630 integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_INVERT_POWER,
    CONF_MAX_REGISTERS,
    CONF_REGISTER_SET,
    CONF_SLAVE_ID,
    CONF_SWAP_IMPORT_EXPORT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MAX_REGISTERS,
    DEFAULT_REGISTER_SET,
    DEFAULT_UPDATE_INTERVAL,
    REGISTER_SET_BASIC,
    REGISTER_SETS,
)
from .coordinator import HA_SDM630Coordinator
from .hub import acquire_hub, release_hub

PLATFORMS = [Platform.SENSOR]

type SDM630ConfigEntry = ConfigEntry[HA_SDM630Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SDM630ConfigEntry) -> bool:
    """Set up SDM630 from a config entry."""
    # Options can be changed without re-adding the meter
    register_set_key = entry.options.get(CONF_REGISTER_SET, DEFAULT_REGISTER_SET)
    selected_registers = REGISTER_SETS.get(register_set_key, REGISTER_SETS[REGISTER_SET_BASIC])
    update_interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    # Meters on the same serial bus / TCP gateway share one connection
    hub = acquire_hub(hass, entry.data, entry.entry_id)

    coordinator = HA_SDM630Coordinator(
        hass,
        hub.client,
        entry.data[CONF_SLAVE_ID],
        selected_registers,
        timedelta(seconds=update_interval),
        invert_power=entry.options.get(CONF_INVERT_POWER, False),
        swap_import_export=entry.options.get(CONF_SWAP_IMPORT_EXPORT, False),
        lock=hub.lock,
        config_entry=entry,
        name=f"SDM630 {entry.title}",
        max_registers=entry.options.get(CONF_MAX_REGISTERS, DEFAULT_MAX_REGISTERS),
    )
    coordinator.hub = hub

    # First data refresh. Don't fail setup when the meter is unreachable (bus not
    # powered yet, USB adapter missing, gateway down): the sensors start as
    # unavailable and the coordinator retries every STARTUP_RETRY_INTERVAL.
    await coordinator.async_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SDM630ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    release_hub(hass, entry.runtime_data.hub, entry.entry_id)
    return True


async def update_listener(hass: HomeAssistant, entry: SDM630ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
