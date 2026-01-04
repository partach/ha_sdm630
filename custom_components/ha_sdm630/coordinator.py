"""Data update coordinator for SDM630 with proper async handling."""

import logging
import struct
import asyncio
from datetime import timedelta
from typing import Dict

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pymodbus.exceptions import ModbusException, ConnectionException

_LOGGER = logging.getLogger(__name__)

# Reduce noise from pymodbus
# Setting parent logger to CRITICAL to catch all sub-loggers
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
logging.getLogger("pymodbus.logging").setLevel(logging.CRITICAL)


class HA_SDM630Coordinator(DataUpdateCoordinator):
    def __init__(self, hass, client, slave_id: int, register_map: dict, update_interval: timedelta = timedelta(seconds=10)):
        super().__init__(
            hass,
            _LOGGER,
            name="SDM630",
            update_interval=update_interval,
        )
        self.client = client  # ← Shared client (only used for settings in TCP case if we force new connection)
        self.slave_id = slave_id
        self.register_map = register_map
        # Limit max registers to 4 to avoid gateway fragmentation issues
        self._address_groups = self._group_addresses(register_map, max_registers=4)
        self.update_interval = update_interval

    def _group_addresses(self, reg_map: dict, max_registers: int = 4) -> Dict[int, list]:
        """Group consecutive register addresses to minimize requests."""
        addresses = sorted([(info["address"], key) for key, info in reg_map.items()])
        groups = {}
        current_start = None
        current_keys = []

        for addr, key in addresses:
            if current_start is None:
                current_start = addr
                current_keys = [key]
            else:
                current_size = len(current_keys) * 2
                # Check for continuity AND max size
                if (addr == current_start + current_size) and (current_size + 2 <= max_registers):
                    current_keys.append(key)
                else:
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

    async def _async_update_data(self) -> dict:
        """Fetch all data in batched async reads."""
        new_data = {}

        # Ensure we start with a clean connection if possible
        if not await self._async_connect():
            raise UpdateFailed("Failed to connect to SDM630")

        try:
            for start_addr, keys in self._address_groups.items():
                count = len(keys) * 2  # 2 registers per float
                
                try:
                    result = await self.client.read_input_registers(
                        address=start_addr,
                        count=count,
                        device_id=self.slave_id,
                    )
                except ModbusException as e:
                    # Log as debug to reduce noise for expected transient errors
                    _LOGGER.debug(f"Modbus error reading address {start_addr}: {e}")
                    # Force reconnect on error to clear transaction ID mismatches
                    self.client.close()
                    await asyncio.sleep(0.5)
                    await self._async_connect()
                    continue

                if result.isError():
                    _LOGGER.debug(f"Read error at {start_addr}: {result}")
                    self.client.close()
                    await asyncio.sleep(0.5)
                    await self._async_connect()
                    continue
        
                registers = result.registers
        
                for i, key in enumerate(keys):
                    reg_offset = i * 2
                    if reg_offset + 1 >= len(registers):
                        break

                    reg1 = registers[reg_offset]
                    reg2 = registers[reg_offset + 1]
        
                    # ---- SDM630 mixed word-order handling ----
                    order = self.register_map[key].get("word_order", "AB")
        
                    if order == "AB":
                        raw = struct.pack(">HH", reg1, reg2)
                    elif order == "BA":
                        raw = struct.pack(">HH", reg2, reg1)
                    else:
                        raise ValueError(f"Unknown word_order '{order}' for {key}")
        
                    value = struct.unpack(">f", raw)[0]
                    # -----------------------------------------
        
                    # Handle NaN / invalid values
                    if value != value:  # NaN check
                        value = None
                    else:
                        precision = self.register_map[key].get("precision", 2)
                        value = round(value, precision)
        
                    new_data[key] = value

                # Small delay between requests to allow gateway buffer to clear
                await asyncio.sleep(0.1)
        
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
            # OPTIONAL: Close connection after every full cycle if the gateway is VERY unstable
            # self.client.close()
            pass
