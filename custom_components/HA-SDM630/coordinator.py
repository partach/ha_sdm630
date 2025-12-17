"""Data update coordinator for SDM630 with proper async handling."""

import logging
import struct
from datetime import timedelta
from typing import Dict

from homeassistant.exceptions import UpdateFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException, ConnectionException

from .const import VALIDATED_REGISTER_MAP as REGISTER_MAP

_LOGGER = logging.getLogger(__name__)


class SDM630Coordinator(DataUpdateCoordinator):
    """SDM630 data coordinator using async Modbus client."""

    def __init__(self, hass, port: str, slave_id: int, baudrate: int):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="SDM630",
            update_interval=timedelta(seconds=update_interval),
        )

        self.port = port
        self.slave_id = slave_id
        self.baudrate = baudrate

        # Use async serial client
        self.client = AsyncModbusSerialClient(
            port=port,
            baudrate=baudrate,
            parity="N",
            stopbits=1,
            bytesize=8,
            timeout=5,
        )

        # Pre-calculate address groups for batch reading
        self._address_groups = self._group_addresses()

    def _group_addresses(self) -> Dict[int, list]:
        """Group consecutive register addresses to minimize requests."""
        addresses = sorted([(info["address"], key) for key, info in REGISTER_MAP.items()])
        groups = {}
        current_start = None
        current_keys = []

        for addr, key in addresses:
            if current_start is None:
                current_start = addr
                current_keys = [key]
            elif addr == current_start + len(current_keys) * 2:  # Consecutive (2 regs per float)
                current_keys.append(key)
            else:
                # Save previous group
                groups[current_start] = current_keys
                current_start = addr
                current_keys = [key]

        # Save last group
        if current_start is not None:
            groups[current_start] = current_keys

        return groups

    async def _async_connect(self) -> bool:
        """Connect to the device."""
        try:
            if not self.client.connected:
                await self.client.connect()
            return self.client.connected
        except Exception as err:
            _LOGGER.debug("Failed to connect to SDM630: %s", err)
            return False

    async def async_test_connection(self) -> bool:
        """Test connection during config flow."""
        try:
            if await self._async_connect():
                # Try reading one known register
                result = await self.client.read_input_registers(0, 2, slave=self.slave_id)
                return not result.isError()
        except Exception as err:
            _LOGGER.debug("Connection test failed: %s", err)
        finally:
            await self.client.close()
        return False

    async def _async_update_data(self) -> dict:
        """Fetch all data in batched async reads."""
        if not await self._async_connect():
            raise UpdateFailed("Failed to connect to SDM630")

        new_data = {}

        try:
            for start_addr, keys in self._address_groups.items():
                count = len(keys) * 2  # 2 registers per float

                result = await self.client.read_input_registers(
                    address=start_addr,
                    count=count,
                    slave=self.slave_id,
                )

                if result.isError():
                    raise ModbusException(f"Read error at {start_addr}: {result}")

                registers = result.registers

                for i, key in enumerate(keys):
                    reg_offset = i * 2
                    reg1 = registers[reg_offset]
                    reg2 = registers[reg_offset + 1]

                    # Convert to big-endian float
                    raw = struct.pack(">HH", reg1, reg2)
                    value = struct.unpack(">f", raw)[0]

                    # Handle NaN/invalid values
                    if value is None or (value != value):  # NaN check
                        value = None
                    else:
                        precision = REGISTER_MAP[key].get("precision", 2)
                        value = round(value, precision)

                    new_data[key] = value

            return new_data

        except ConnectionException as err:
            # Force reconnect next time
            await self.client.close()
            raise UpdateFailed(f"Connection lost: {err}")

        except ModbusException as err:
            raise UpdateFailed(f"Modbus error: {err}")

        except Exception as err:
            _LOGGER.error("Unexpected error during SDM630 update: %s", err)
            raise UpdateFailed(f"Update failed: {err}")

        finally:
            # Keep connection open for next poll (async client handles it well)
            pass
