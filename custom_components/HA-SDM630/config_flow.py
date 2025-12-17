"""Config flow for SDM630 integration."""

import logging
from typing import Any

import serial.tools.list_ports
import voluptuous as vol
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException, ConnectionException

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_BAUDRATE,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    DEFAULT_BAUDRATE,
    DEFAULT_SLAVE_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class HA_SDM630ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SDM630."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Discover serial ports every time (in case plugged/unplugged)
        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)

        port_options = [
            selector.SelectOptionDict(
                value=port.device,
                label=(
                    f"{port.device} - {port.description or 'Unknown device'}"
                    + (f" ({port.manufacturer})" if port.manufacturer else "")
                ),
            )
            for port in ports
            if port.device
        ]
        port_options.sort(key=lambda x: x["value"])

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="SDM630"): str,
                vol.Required(CONF_SERIAL_PORT): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=port_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=247)
                ),
                vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In(
                    [2400, 4800, 9600, 19200, 38400]
                ),
            }
        )

        if user_input is not None:
            try:
                await self._async_test_connection(user_input)

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_SERIAL_PORT: user_input[CONF_SERIAL_PORT],
                        CONF_SLAVE_ID: user_input[CONF_SLAVE_ID],
                        CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                    },
                )

            except ConnectionError:
                errors["base"] = "cannot_connect"
            except ModbusException:
                errors["base"] = "read_error"
            except ValueError:
                errors["base"] = "read_error"
            except Exception as err:
                errors["base"] = "unknown"
                _LOGGER.exception("Unexpected error during SDM630 setup: %s", err)

        # Show form on first load or after error
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def _async_test_connection(self, data: dict[str, Any]) -> None:
        """Test connection to the SDM630 meter."""
        client = AsyncModbusSerialClient(
            port=data[CONF_SERIAL_PORT],
            baudrate=data[CONF_BAUDRATE],
            parity="N",
            stopbits=1,
            bytesize=8,
            timeout=5,
        )
        try:
            await client.connect()
            if not client.connected:
                raise ConnectionError("Failed to open serial port")

            result = await client.read_input_registers(
                address=0, count=2, slave=data[CONF_SLAVE_ID]
            )

            if result.isError():
                raise ModbusException(f"Modbus read error: {result}")

            if len(result.registers) != 2:
                raise ValueError("Invalid response: expected 2 registers")

        finally:
            await client.close()
