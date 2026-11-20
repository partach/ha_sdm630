"""Data update coordinator for SDM630 with proper async handling."""

import asyncio
import logging
import struct
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pymodbus.exceptions import ModbusException

from .const import (
    IMPORT_EXPORT_PAIRS,
    INVERTIBLE_POWER_KEYS,
    MAX_CONSECUTIVE_READ_ERRORS,
    RUNTIME_RETRY_INTERVALS,
    STARTUP_RETRY_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Reduce noise from pymodbus
# Setting parent logger to CRITICAL to catch all sub-loggers
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
logging.getLogger("pymodbus.logging").setLevel(logging.CRITICAL)

# Modbus exception codes a TCP gateway sends when the meter behind it is silent
_GATEWAY_NO_RESPONSE_CODES = (0x0A, 0x0B)


class MeterUnavailable(Exception):
    """The meter (or the bus/gateway in front of it) cannot be reached."""


class HA_SDM630Coordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass,
        client,
        slave_id: int,
        register_map: dict,
        update_interval: timedelta = timedelta(seconds=10),
        invert_power: bool = False,
        swap_import_export: bool = False,
        lock: asyncio.Lock | None = None,
        config_entry=None,
        name: str = "SDM630",
    ):
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=name,
            update_interval=update_interval,
        )
        self.client = client  # ← Shared client
        self.slave_id = slave_id
        self.register_map = register_map
        self._address_groups = self._group_addresses(register_map, max_registers=4)  # Use passed map
        self.update_interval = update_interval
        self.invert_power = invert_power
        self.swap_import_export = swap_import_export
        # Serialises whole poll cycles of all meters that share one bus/connection,
        # so one meter can't close the connection while another is reading.
        self._lock = lock or asyncio.Lock()
        self._normal_interval = update_interval
        self._failed_polls = 0
        self._has_connected = False

    def _group_addresses(self, reg_map: dict, max_registers=4) -> dict[int, list]:
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

    def _apply_direction_correction(self, data: dict) -> dict:
        """Correct readings from a meter whose current direction is reversed."""
        if self.invert_power:
            for key in INVERTIBLE_POWER_KEYS:
                value = data.get(key)
                if value is not None:
                    # "+ 0.0" turns -0.0 into 0.0
                    data[key] = -value + 0.0
        if self.swap_import_export:
            for import_key, export_key in IMPORT_EXPORT_PAIRS:
                if import_key in data or export_key in data:
                    data[import_key], data[export_key] = (
                        data.get(export_key),
                        data.get(import_key),
                    )
        return data

    def _retry_interval(self) -> timedelta:
        """Pick the wait before the next attempt after a failed poll."""
        if not self._has_connected:
            # Never reached the meter since setup: retry at a slow, fixed pace
            retry = STARTUP_RETRY_INTERVAL
        else:
            step = min(self._failed_polls, len(RUNTIME_RETRY_INTERVALS)) - 1
            retry = RUNTIME_RETRY_INTERVALS[step]
        return max(retry, self._normal_interval)

    def _close_client(self) -> None:
        """Drop the connection so the next attempt starts clean."""
        try:
            self.client.close()
        except Exception as err:  # noqa: BLE001 - closing must never raise
            _LOGGER.debug("Error closing SDM630 connection: %s", err)

    async def _async_connect(self) -> bool:
        """Connect to the device."""
        try:
            if not self.client.connected:
                await self.client.connect()
            return self.client.connected
        except Exception as err:  # noqa: BLE001 - any failure means "not connected"
            _LOGGER.debug("Failed to connect to SDM630: %s", err)
            return False

    async def _async_update_data(self) -> dict:
        """Poll the meter; on failure back off instead of hammering the bus."""
        try:
            async with self._lock:
                data = await self._async_read_all()
        except MeterUnavailable as err:
            self._failed_polls += 1
            retry = self._retry_interval()
            self.update_interval = retry
            # The coordinator logs the first failure and the recovery; repeats go to debug
            raise UpdateFailed(f"{err}; retrying in {int(retry.total_seconds())} s") from err
        except Exception as err:
            self._failed_polls += 1
            retry = self._retry_interval()
            self.update_interval = retry
            if self._failed_polls == 1:
                _LOGGER.exception("Unexpected error during SDM630 update")
            raise UpdateFailed(
                f"Update failed: {err}; retrying in {int(retry.total_seconds())} s"
            ) from err

        if self._failed_polls:
            _LOGGER.debug(
                "SDM630 slave %s reachable again after %s failed polls",
                self.slave_id,
                self._failed_polls,
            )
        self._failed_polls = 0
        self._has_connected = True
        self.update_interval = self._normal_interval
        return self._apply_direction_correction(data)

    async def _async_read_all(self) -> dict:
        """Read every register group in one pass."""
        if not await self._async_connect():
            raise MeterUnavailable(f"Cannot connect to {self.client}")

        new_data = {}
        consecutive_errors = 0
        # While the meter is down (or not reached yet since setup), one failed read
        # ends the attempt, so a dead meter costs one timeout per retry instead of
        # one per register group, and HA startup isn't held up.
        if self._failed_polls or not self._has_connected:
            max_errors = 1
        else:
            max_errors = MAX_CONSECUTIVE_READ_ERRORS

        for start_addr, keys in self._address_groups.items():
            count = len(keys) * 2  # 2 registers per float
            try:
                result = await self.client.read_input_registers(
                    address=start_addr,
                    count=count,
                    device_id=self.slave_id,
                )
            except (ModbusException, asyncio.TimeoutError, OSError) as err:
                consecutive_errors += 1
                _LOGGER.debug("Modbus error reading address %s: %s", start_addr, err)
                # Reconnect to clear transaction ID mismatches / half-open sockets
                self._close_client()
                if consecutive_errors >= max_errors:
                    raise MeterUnavailable(
                        f"No response from SDM630 slave {self.slave_id}: {err}"
                    ) from err
                await asyncio.sleep(0.5)
                if not await self._async_connect():
                    raise MeterUnavailable(f"Cannot reconnect to {self.client}") from err
                continue

            if result.isError():
                if getattr(result, "exception_code", None) in _GATEWAY_NO_RESPONSE_CODES:
                    consecutive_errors += 1
                    _LOGGER.debug("Gateway reports no response at %s: %s", start_addr, result)
                    if consecutive_errors >= max_errors:
                        raise MeterUnavailable(
                            f"Gateway gets no response from SDM630 slave {self.slave_id}"
                        )
                else:
                    # The meter answered but rejected this register (e.g. not on this model)
                    _LOGGER.debug("Read error at %s: %s", start_addr, result)
                continue

            consecutive_errors = 0
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
                if value != value:  # noqa: PLR0124 - NaN check
                    value = None
                else:
                    precision = self.register_map[key].get("precision", 2)
                    value = round(value, precision)

                new_data[key] = value
            # Small delay between requests to allow gateway buffer to clear
            await asyncio.sleep(0.1)

        if not new_data:
            raise MeterUnavailable(f"SDM630 slave {self.slave_id} returned no data")
        return new_data
