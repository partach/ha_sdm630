"""Shared Modbus connections: one per serial bus or TCP gateway."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PARITY,
    CONF_PORT,
    CONF_SERIAL_PORT,
    CONF_STOPBITS,
    CONNECTION_TYPE_SERIAL,
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DEFAULT_TCP_PORT,
    DOMAIN,
    MODBUS_RETRIES,
    MODBUS_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class SDM630Hub:
    """One Modbus client shared by every meter on the same bus or gateway."""

    def __init__(self, key: str, client: AsyncModbusSerialClient | AsyncModbusTcpClient) -> None:
        self.key = key
        self.client = client
        # Serialises poll cycles (and config-flow probes) of all meters on this hub
        self.lock = asyncio.Lock()
        # Config entry ids currently using this hub
        self.users: set[str] = set()

    def close(self) -> None:
        """Close the connection; never raises."""
        try:
            self.client.close()
        except Exception as err:  # noqa: BLE001 - closing must never raise
            _LOGGER.debug("Error closing SDM630 connection %s: %s", self.key, err)


def hub_key(data: Mapping[str, Any]) -> str:
    """Identify the physical connection described by config entry data."""
    if data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL) == CONNECTION_TYPE_SERIAL:
        return (
            f"serial_{data[CONF_SERIAL_PORT]}_{data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)}"
            f"_{data.get(CONF_PARITY, DEFAULT_PARITY)}_{data.get(CONF_STOPBITS, DEFAULT_STOPBITS)}"
            f"_{data.get(CONF_BYTESIZE, DEFAULT_BYTESIZE)}"
        )
    return f"tcp_{data[CONF_HOST]}_{data.get(CONF_PORT, DEFAULT_TCP_PORT)}"


def create_client(data: Mapping[str, Any]) -> AsyncModbusSerialClient | AsyncModbusTcpClient:
    """Build a Modbus client for config entry data (not connected yet)."""
    # Reconnecting is handled by the coordinator (with backoff), not by pymodbus
    common = {"timeout": MODBUS_TIMEOUT, "retries": MODBUS_RETRIES, "reconnect_delay": 0}
    if data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL) == CONNECTION_TYPE_SERIAL:
        return AsyncModbusSerialClient(
            port=data[CONF_SERIAL_PORT],
            baudrate=data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
            parity=data.get(CONF_PARITY, DEFAULT_PARITY),
            stopbits=data.get(CONF_STOPBITS, DEFAULT_STOPBITS),
            bytesize=data.get(CONF_BYTESIZE, DEFAULT_BYTESIZE),
            **common,
        )
    return AsyncModbusTcpClient(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_TCP_PORT),
        **common,
    )


def get_hubs(hass: HomeAssistant) -> dict[str, SDM630Hub]:
    """Return the registry of open hubs."""
    return hass.data.setdefault(DOMAIN, {}).setdefault("hubs", {})


def acquire_hub(hass: HomeAssistant, data: Mapping[str, Any], entry_id: str) -> SDM630Hub:
    """Get (or create) the hub for this connection and register entry_id as a user."""
    hubs = get_hubs(hass)
    key = hub_key(data)
    if key not in hubs:
        hubs[key] = SDM630Hub(key, create_client(data))
    hub = hubs[key]
    hub.users.add(entry_id)
    return hub


def release_hub(hass: HomeAssistant, hub: SDM630Hub, entry_id: str) -> None:
    """Unregister entry_id; close the connection when nobody uses it anymore."""
    hub.users.discard(entry_id)
    if not hub.users:
        get_hubs(hass).pop(hub.key, None)
        hub.close()
        _LOGGER.debug("Closed shared hub %s", hub.key)
