"""The SDM630 integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from pymodbus.client import AsyncModbusSerialClient
from .options_flow import OptionsFlowHandler

from .const import (
    DOMAIN,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_BAUDRATE,
    CONF_REGISTER_SET,
    DEFAULT_REGISTER_SET,
    REGISTER_SETS,
    REGISTER_SET_BASIC,
)
from .coordinator import HA_SDM630Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SDM630 from a config entry."""
    config = entry.data
    # Use options for the register set so users can change it without reinstalling
    register_set_key = entry.options.get(CONF_REGISTER_SET, DEFAULT_REGISTER_SET)
    selected_registers = REGISTER_SETS.get(register_set_key, REGISTER_SETS[REGISTER_SET_BASIC])

    port = config[CONF_SERIAL_PORT]
    baudrate = config[CONF_BAUDRATE]

    # Get or create shared hub for this port + baudrate combination
    hubs = hass.data.setdefault(DOMAIN, {}).setdefault("hubs", {})
    hub_key = f"{port}_{baudrate}"

    if hub_key not in hubs:
        hubs[hub_key] = SDM630Hub(hass, port, baudrate)

    hub = hubs[hub_key]

    # Create coordinator with shared client and selected registers
    coordinator = HA_SDM630Coordinator(
        hass,
        hub.client,
        config[CONF_SLAVE_ID],
        selected_registers
    )
    # Store config for unload cleanup
    coordinator.config = config
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Test connection
    if not await coordinator.async_test_connection():
        raise ConfigEntryNotReady("Could not connect to SDM630")

    # First data refresh
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_get_options_flow(config_entry: ConfigEntry):
    """Return the options flow handler."""
    return OptionsFlowHandler(config_entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator = hass.data[DOMAIN].pop(entry.entry_id)

    # Clean up hub if no other entries use the same port + baudrate
    config = coordinator.config
    port = config[CONF_SERIAL_PORT]
    baudrate = config[CONF_BAUDRATE]
    hub_key = f"{port}_{baudrate}"

    # Check if any other active entries still use this hub
    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
        and e.data.get(CONF_SERIAL_PORT) == port
        and e.data.get(CONF_BAUDRATE) == baudrate
    ]

    if not remaining:
        hub = hass.data[DOMAIN]["hubs"].pop(hub_key, None)
        if hub:
            await hub.close()

    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)

class SDM630Hub:
    """Manages a single serial connection shared across meters."""

    def __init__(self, hass: HomeAssistant, port: str, baudrate: int):
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
        """Close the serial connection."""
        if self.client.connected:
            await self.client.close()
