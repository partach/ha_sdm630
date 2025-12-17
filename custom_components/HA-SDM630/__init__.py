"""The SDM630 integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from pymodbus.client import AsyncModbusSerialClient

from .const import (
    DOMAIN,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_BAUDRATE,
#    CONF_UPDATE_INTERVAL,
#    DEFAULT_UPDATE_INTERVAL,
)
from .coordinator import HA_SDM630Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    config = entry.data

    port = config[CONF_SERIAL_PORT]
    baudrate = config[CONF_BAUDRATE]

    # Get or create shared hub for this port
    hubs = hass.data.setdefault(DOMAIN, {}).setdefault("hubs", {})
    hub_key = f"{port}_{baudrate}"
    if hub_key not in hubs:
        hubs[hub_key] = SDM630Hub(hass, port, baudrate)

    hub = hubs[hub_key]

    coordinator = HA_SDM630Coordinator(
        hass,
        hub.client,  # ← Pass shared client
        config[CONF_SLAVE_ID],
    )
    coordinator.config = config  # Save for later unload
    # Test connection
    if not await coordinator.async_test_connection():
        raise ConfigEntryNotReady("Could not connect to SDM630")

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)

        # Clean up hub if no more entries use this port
        config = coordinator.config  # You'll need to store config in coordinator
        port = config[CONF_SERIAL_PORT]
        baudrate = config[CONF_BAUDRATE]
        hub_key = f"{port}_{baudrate}"

        remaining = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id  # Exclude current one
            and e.data[CONF_SERIAL_PORT] == port
            and e.data[CONF_BAUDRATE] == baudrate
        ]
        if not remaining:
            hub = hass.data[DOMAIN]["hubs"].pop(hub_key, None)
            if hub:
                await hub.close()

    return unload_ok

class SDM630Hub:
    """Manages a single serial connection shared across meters."""

    def __init__(self, hass, port: str, baudrate: int):
        self.hass = hass
        self.port = port
        self.baudrate = baudrate
        self.client = AsyncModbusSerialClient(
            port=port,
            baudrate=baudrate,
            parity="N",
            stopbits=1,
            bytesize=8,
            timeout=5,
        )

    async def close(self):
        if self.client.connected:
            await self.client.close()
