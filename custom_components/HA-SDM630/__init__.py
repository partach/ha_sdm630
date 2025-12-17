"""The SDM630 integration."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_BAUDRATE,
#    CONF_UPDATE_INTERVAL,
#    DEFAULT_UPDATE_INTERVAL,
)
from .coordinator import SDM630Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SDM630 from a config entry."""
    config = entry.data

    # Create coordinator for polling
    coordinator = SDM630Coordinator(
        hass,
        config[CONF_SERIAL_PORT],
        config[CONF_SLAVE_ID],
        config[CONF_BAUDRATE],
    )

    # Test connection before proceeding
    if not await coordinator.async_test_connection():
        raise ConfigEntryNotReady("Could not connect to SDM630")

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Set up platforms (sensors)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
