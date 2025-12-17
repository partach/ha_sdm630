"""Data update coordinator for SDM630."""

import logging
from datetime import timedelta

from homeassistant.exceptions import UpdateFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pymodbus.client import ModbusSerialClient
from pymodbus.pdu import ModbusExceptions as exc

from .const import REGISTER_MAP

_LOGGER = logging.getLogger(__name__)


class SDM630Coordinator(DataUpdateCoordinator):
    """SDM630 data coordinator."""

    def __init__(self, hass, port, slave_id, baudrate, update_interval):
        super().__init__(
            hass,
            _LOGGER,
            name="SDM630",
            update_interval=timedelta(seconds=update_interval),
        )
        self.client = ModbusSerialClient(
            port=port,
            baudrate=baudrate,
            parity="N",
            stopbits=1,
            bytesize=8,
            timeout=3,
        )
        self.slave_id = slave_id
        self.data = {}  # Store polled values

    async def async_test_connection(self) -> bool:
        """Test connection for config flow."""
        try:
            await self._async_update_data()
            return True
        except Exception:
            return False

    async def _async_update_data(self) -> dict:
        """Fetch data from SDM630."""
        try:
            if not self.client.connected:
                self.client.connect()

            new_data = {}
            for key, info in REGISTER_MAP.items():
                rr = self.client.read_holding_registers(info["address"], 2, slave=self.slave_id)  # Floats are 2 regs
                if rr.isError():
                    if isinstance(rr, exc.ConnectionException):
                        self.client.close()
                    raise UpdateFailed(f"Read error for {key}: {rr}")
                # Convert registers to float (SDM630 uses IEEE 754)
                value = (rr.registers[0] << 16) + rr.registers[1]
                value = int.from_bytes(value.to_bytes(4, "big"), "big", signed=True) / 100.0  # Example scaling; adjust per reg
                new_data[key] = value

            self.data = new_data
            return new_data
        except Exception as err:
            raise UpdateFailed(f"Update failed: {err}")
