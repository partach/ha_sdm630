"""Config flow for SDM630 integration."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

import serial.tools.list_ports
import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from pymodbus.exceptions import ModbusException

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_FRAMER,
    CONF_HOST,
    CONF_INVERT_POWER,
    CONF_MAX_REGISTERS,
    CONF_PARITY,
    CONF_PORT,
    CONF_REGISTER_SET,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_STOPBITS,
    CONF_SWAP_IMPORT_EXPORT,
    CONF_UPDATE_INTERVAL,
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_MAX_REGISTERS,
    DEFAULT_PARITY,
    DEFAULT_REGISTER_SET,
    DEFAULT_SLAVE_ID,
    DEFAULT_STOPBITS,
    DEFAULT_TCP_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FRAMER_RTU,
    FRAMER_SOCKET,
    REGISTER_SET_BASIC,
    REGISTER_SET_BASIC_PLUS,
    REGISTER_SET_FULL,
)
from .hub import create_client, get_hubs, hub_key

_LOGGER = logging.getLogger(__name__)

_SERIAL_BY_ID = "/dev/serial/by-id"

_SLAVE_ID_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=1, max=247))

# Connection fields per connection type (everything except the name)
_SERIAL_FIELDS = (CONF_SERIAL_PORT, CONF_SLAVE_ID, CONF_BAUDRATE, CONF_PARITY, CONF_STOPBITS, CONF_BYTESIZE)
_TCP_FIELDS = (CONF_HOST, CONF_PORT, CONF_FRAMER, CONF_SLAVE_ID)


def _list_serial_ports() -> list[selector.SelectOptionDict]:
    """List serial ports, preferring stable /dev/serial/by-id paths (blocking I/O)."""
    by_id: dict[str, str] = {}
    if os.path.isdir(_SERIAL_BY_ID):
        for name in os.listdir(_SERIAL_BY_ID):
            link = os.path.join(_SERIAL_BY_ID, name)
            by_id[os.path.realpath(link)] = link

    options = []
    for port in serial.tools.list_ports.comports():
        if not port.device:
            continue
        # ttyUSB0/ttyUSB1 can swap after a reboot; the by-id path stays the same
        path = by_id.get(os.path.realpath(port.device), port.device)
        label = f"{path} - {port.description or 'Unknown device'}"
        if port.manufacturer:
            label += f" ({port.manufacturer})"
        options.append(selector.SelectOptionDict(value=path, label=label))
    return sorted(options, key=lambda option: option["value"])


def _serial_schema(port_options: list[selector.SelectOptionDict], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default="SDM630")] = str
    fields.update(
        {
            vol.Required(CONF_SERIAL_PORT): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=port_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    # Allow typing a path that isn't listed
                    custom_value=True,
                )
            ),
            vol.Required(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID): _SLAVE_ID_SCHEMA,
            vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In([2400, 4800, 9600, 19200, 38400]),
            vol.Required(CONF_PARITY, default=DEFAULT_PARITY): vol.In(["N", "E", "O"]),
            vol.Required(CONF_STOPBITS, default=DEFAULT_STOPBITS): vol.In([1, 2]),
            vol.Required(CONF_BYTESIZE, default=DEFAULT_BYTESIZE): vol.In([7, 8]),
        }
    )
    return vol.Schema(fields)


def _tcp_schema(with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default="SDM630")] = str
    fields.update(
        {
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_FRAMER, default=FRAMER_SOCKET): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=FRAMER_SOCKET, label="Modbus TCP"),
                        selector.SelectOptionDict(value=FRAMER_RTU, label="RTU over TCP (transparent RS485 converter)"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID): _SLAVE_ID_SCHEMA,
        }
    )
    return vol.Schema(fields)


def _meter_unique_id(data: Mapping[str, Any]) -> str:
    """One config entry per meter: same port/host and same Modbus address."""
    if data[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_SERIAL:
        return f"serial_{data[CONF_SERIAL_PORT]}_{data[CONF_SLAVE_ID]}"
    return f"tcp_{data[CONF_HOST]}:{data[CONF_PORT]}_{data[CONF_SLAVE_ID]}"


class HA_SDM630ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SDM630."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> SDM630OptionsFlowHandler:
        """Get the options flow for this handler."""
        return SDM630OptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle connection type selection."""
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_SERIAL:
                return await self.async_step_serial()
            return await self.async_step_tcp()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_SERIAL): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=CONNECTION_TYPE_SERIAL, label="Serial (RS485)"),
                            selector.SelectOptionDict(value=CONNECTION_TYPE_TCP, label="TCP/IP (Modbus TCP gateway)"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle serial connection configuration."""
        return await self._async_connection_step("serial", CONNECTION_TYPE_SERIAL, user_input)

    async def async_step_tcp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle TCP connection configuration."""
        return await self._async_connection_step("tcp", CONNECTION_TYPE_TCP, user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the connection of an existing meter (port, host, address, ...)."""
        entry = self._get_reconfigure_entry()
        if entry.data[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_SERIAL:
            return await self._async_connection_step("reconfigure_serial", CONNECTION_TYPE_SERIAL, user_input)
        return await self._async_connection_step("reconfigure_tcp", CONNECTION_TYPE_TCP, user_input)

    async def async_step_reconfigure_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Submit target of the serial reconfigure form."""
        return await self._async_connection_step("reconfigure_serial", CONNECTION_TYPE_SERIAL, user_input)

    async def async_step_reconfigure_tcp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Submit target of the TCP reconfigure form."""
        return await self._async_connection_step("reconfigure_tcp", CONNECTION_TYPE_TCP, user_input)

    async def _async_connection_step(
        self, step_id: str, connection_type: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Show/validate a serial or TCP form, for a new meter or a reconfigure."""
        reconfigure = self.source == SOURCE_RECONFIGURE
        entry = self._get_reconfigure_entry() if reconfigure else None
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {CONF_CONNECTION_TYPE: connection_type, **user_input}
            unique_id = _meter_unique_id(data)
            if reconfigure:
                if any(
                    other.unique_id == unique_id and other.entry_id != entry.entry_id
                    for other in self._async_current_entries(include_ignore=False)
                ):
                    return self.async_abort(reason="already_configured")
            else:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

            if await self._async_validate(data, errors):
                if reconfigure:
                    return self.async_update_reload_and_abort(
                        entry, unique_id=unique_id, data_updates=user_input
                    )
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        if connection_type == CONNECTION_TYPE_SERIAL:
            # Discover serial ports every time (in case plugged/unplugged)
            port_options = await self.hass.async_add_executor_job(_list_serial_ports)
            schema = _serial_schema(port_options, with_name=not reconfigure)
        else:
            schema = _tcp_schema(with_name=not reconfigure)

        suggested = user_input
        if suggested is None and entry is not None:
            fields = _SERIAL_FIELDS if connection_type == CONNECTION_TYPE_SERIAL else _TCP_FIELDS
            suggested = {key: entry.data[key] for key in fields if key in entry.data}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def _async_validate(self, data: dict[str, Any], errors: dict[str, str]) -> bool:
        """Test the meter; fill errors and return False on failure."""
        try:
            await self._async_test_connection(data)
        except ConnectionError:
            errors["base"] = "cannot_connect"
        except (ModbusException, ValueError):
            errors["base"] = "read_error"
        except Exception:
            errors["base"] = "unknown"
            _LOGGER.exception("Unexpected error during SDM630 setup")
        else:
            return True
        return False

    async def _async_test_connection(self, data: dict[str, Any]) -> None:
        """Read one register from the meter to prove the settings work."""
        hub = get_hubs(self.hass).get(hub_key(data))
        if hub is not None:
            # This bus/gateway is already open: probe through it, so the port
            # isn't opened twice and the probe doesn't collide with polling
            async with hub.lock:
                await self._async_probe(hub.client, data)
            return

        client = create_client(data)
        try:
            await self._async_probe(client, data)
        finally:
            client.close()

    @staticmethod
    async def _async_probe(client, data: dict[str, Any]) -> None:
        if not client.connected:
            await client.connect()
        if not client.connected:
            raise ConnectionError(f"Cannot connect to {client}")
        result = await client.read_input_registers(
            address=0, count=2, device_id=data[CONF_SLAVE_ID]
        )
        if result.isError():
            raise ModbusException(f"Modbus read error: {result}")
        if len(result.registers) != 2:
            raise ValueError("Invalid response: expected 2 registers")


class SDM630OptionsFlowHandler(OptionsFlow):
    """Options: register set, polling, direction correction."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_REGISTER_SET,
                    default=options.get(CONF_REGISTER_SET, DEFAULT_REGISTER_SET),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=REGISTER_SET_BASIC,
                                label="Basic (Essential sensors, fastest, low overhead)",
                            ),
                            selector.SelectOptionDict(
                                value=REGISTER_SET_BASIC_PLUS,
                                label="Basic+ (adds VA, PF, neutral, if you need it)",
                            ),
                            selector.SelectOptionDict(
                                value=REGISTER_SET_FULL,
                                label="Full (All registers, slowest, heavy)",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=5, max=300),  # 5 seconds to 5 minutes
                ),
                vol.Required(
                    CONF_MAX_REGISTERS,
                    default=options.get(CONF_MAX_REGISTERS, DEFAULT_MAX_REGISTERS),
                ): vol.All(vol.Coerce(int), vol.Range(min=2, max=80)),
                vol.Required(
                    CONF_INVERT_POWER,
                    default=options.get(CONF_INVERT_POWER, False),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_SWAP_IMPORT_EXPORT,
                    default=options.get(CONF_SWAP_IMPORT_EXPORT, False),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
