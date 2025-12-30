"""The SDM630 integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient

from .const import (
    DOMAIN,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PARITY,
    CONF_PORT,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_STOPBITS,
    CONF_REGISTER_SET,
    CONNECTION_TYPE_SERIAL,
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_REGISTER_SET,
    DEFAULT_STOPBITS,
    REGISTER_SETS,
    REGISTER_SET_BASIC,
)
from .coordinator import HA_SDM630Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SDM630 from a config entry."""
    config = entry.data
    connection_type = config.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL)
    
    # Use options for the register set so users can change it without reinstalling
    register_set_key = entry.options.get(CONF_REGISTER_SET, DEFAULT_REGISTER_SET)
    selected_registers = REGISTER_SETS.get(register_set_key, REGISTER_SETS[REGISTER_SET_BASIC])

    # Get or create shared hub for this connection
    hubs = hass.data.setdefault(DOMAIN, {}).setdefault("hubs", {})
    
    if connection_type == CONNECTION_TYPE_SERIAL:
        port = config[CONF_SERIAL_PORT]
        baudrate = config.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
        parity = config.get(CONF_PARITY, DEFAULT_PARITY)
        stopbits = config.get(CONF_STOPBITS, DEFAULT_STOPBITS)
        bytesize = config.get(CONF_BYTESIZE, DEFAULT_BYTESIZE)
        hub_key = f"serial_{port}_{baudrate}_{parity}_{stopbits}_{bytesize}"
        
        if hub_key not in hubs:
            hubs[hub_key] = SDM630SerialHub(hass, port, baudrate, parity, stopbits, bytesize)
    else:  # TCP
        host = config[CONF_HOST]
        port = config[CONF_PORT]
        hub_key = f"tcp_{host}_{port}"
        
        if hub_key not in hubs:
            hubs[hub_key] = SDM630TcpHub(hass, host, port)

    hub = hubs[hub_key]
    update_interval = config_entry.options.get(CONF_UPDATE_INTERVAL, timedelta(seconds=10))
    # Create coordinator with shared client and selected registers
    coordinator = HA_SDM630Coordinator(
        hass,
        hub.client,
        config[CONF_SLAVE_ID],
        selected_registers,
        update_interval
    )
    # Store config and hub_key for unload cleanup
    coordinator.config = config
    coordinator.hub_key = hub_key

    entry.async_on_unload(entry.add_update_listener(update_listener))

    # First data refresh
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    # Remove coordinator
    coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
    if not coordinator:
        return True  # Already cleaned up

    hub_key = getattr(coordinator, "hub_key", None)
    if not hub_key:
        return True

    # Check if any other active entries still use this hub
    hub_still_used = any(
        getattr(hass.data[DOMAIN].get(e.entry_id), "hub_key", None) == hub_key
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    )

    if not hub_still_used:
        hub = hass.data[DOMAIN]["hubs"].pop(hub_key, None)
        if hub:
            try:
                await hub.close()
                _LOGGER.debug("Closed shared hub %s during unload", hub_key)
            except Exception as err:
                _LOGGER.warning("Error closing hub %s: %s", hub_key, err)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class SDM630SerialHub:
    """Manages a single serial connection shared across meters."""

    def __init__(
        self,
        hass: HomeAssistant,
        port: str,
        baudrate: int,
        parity: str,
        stopbits: int,
        bytesize: int,
    ):
        self.hass = hass
        self.port = port
        self.baudrate = baudrate
        self.parity = parity
        self.stopbits = stopbits
        self.bytesize = bytesize
        self.client = AsyncModbusSerialClient(
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=5,
        )

    async def close(self):
        """Close the connection safely."""
        if self.client is not None:
            if self.client.connected:
                try:
                    self.client.close()
                    _LOGGER.debug("Successfully closed SDM630 connection")
                except Exception as err:
                    _LOGGER.exception("Unexpected error closing SDM630 connection: %s", err)
            else:
                _LOGGER.debug("SDM630 client was already disconnected")
            # Always nil out the client to prevent reuse
            self.client = None
        else:
            _LOGGER.debug("SDM630 client was already None - nothing to close")


class SDM630TcpHub:
    """Manages a single TCP connection shared across meters."""

    def __init__(self, hass: HomeAssistant, host: str, port: int):
        self.hass = hass
        self.host = host
        self.port = port
        self.client = AsyncModbusTcpClient(
            host=host,
            port=port,
            timeout=5,
        )

    async def close(self):
        """Close the connection safely."""
        if self.client is not None:
            if self.client.connected:
                try:
                    self.client.close()
                except Exception as err:
                    _LOGGER.exception("Unexpected error closing SDM630 connection for tcp: %s", err)
