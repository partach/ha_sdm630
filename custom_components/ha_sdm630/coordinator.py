"""Data update coordinator for SDM630 with proper async handling."""

from __future__ import annotations

import asyncio
import logging
import math
import struct
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pymodbus.exceptions import ModbusException

from .const import (
    DEFAULT_MAX_REGISTERS,
    IMPORT_EXPORT_PAIRS,
    INVERTIBLE_POWER_KEYS,
    MAX_CONSECUTIVE_READ_ERRORS,
    MAX_READ_GAP,
    RUNTIME_RETRY_INTERVALS,
    STARTUP_RETRY_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# pymodbus logs every failed connect/read itself. Keep it quiet by default, but
# don't override a level the user set (logger: in configuration.yaml), and keep
# the HA built-in Modbus integration's logging untouched when it is configured.
_PYMODBUS_LOGGER = logging.getLogger("pymodbus")
if _PYMODBUS_LOGGER.level == logging.NOTSET:
    _PYMODBUS_LOGGER.setLevel(logging.CRITICAL)

# Modbus exception codes a TCP gateway sends when the meter behind it is silent
_GATEWAY_NO_RESPONSE_CODES = (0x0A, 0x0B)
# Exception codes meaning "this address range/size is not readable": split the read
_ILLEGAL_RANGE_CODES = (0x02, 0x03)


class MeterUnavailable(Exception):
    """The meter (or the bus/gateway in front of it) cannot be reached."""


@dataclass
class ReadBlock:
    """One read request: a register range and the values inside it."""

    start: int
    count: int
    # (key, register offset inside the block)
    keys: list[tuple[str, int]] = field(default_factory=list)


def plan_reads(
    register_map: dict, max_registers: int = DEFAULT_MAX_REGISTERS, max_gap: int = MAX_READ_GAP
) -> list[ReadBlock]:
    """Group registers into as few read requests as the limits allow.

    Registers closer than max_gap are read together (the unused registers in
    between are read and ignored); a request never exceeds max_registers.
    """
    blocks: list[ReadBlock] = []
    for key, info in sorted(register_map.items(), key=lambda item: item[1]["address"]):
        addr = info["address"]
        if blocks:
            block = blocks[-1]
            end = block.start + block.count
            if addr >= end and addr - end <= max_gap and addr + 2 - block.start <= max_registers:
                block.count = addr + 2 - block.start
                block.keys.append((key, addr - block.start))
                continue
        blocks.append(ReadBlock(addr, 2, [(key, 0)]))
    return blocks


def _decode_float(reg1: int, reg2: int) -> float:
    return struct.unpack(">f", struct.pack(">HH", reg1, reg2))[0]


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
        max_registers: int = DEFAULT_MAX_REGISTERS,
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
        self._blocks = plan_reads(register_map, max_registers)
        self.invert_power = invert_power
        self.swap_import_export = swap_import_export
        # Serialises whole poll cycles of all meters that share one bus/connection,
        # so one meter can't close the connection while another is reading.
        self._lock = lock or asyncio.Lock()
        self._normal_interval = update_interval
        self._failed_polls = 0
        self._has_connected = False

    @property
    def read_requests(self) -> int:
        """Number of read requests per poll."""
        return len(self._blocks)

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

    def _split_block(self, block: ReadBlock) -> list[ReadBlock]:
        """Replace a multi-value block by single-value reads (for this session)."""
        singles = [ReadBlock(block.start + offset, 2, [(key, 0)]) for key, offset in block.keys]
        index = self._blocks.index(block)
        self._blocks[index : index + 1] = singles
        _LOGGER.debug(
            "SDM630 slave %s rejected a %s-register read at %s; reading those %s values one by one",
            self.slave_id,
            block.count,
            block.start,
            len(singles),
        )
        return singles

    async def _async_read_all(self) -> dict:
        """Read every register block in one pass."""
        if not await self._async_connect():
            raise MeterUnavailable(f"Cannot connect to {self.client}")

        raw: dict[str, tuple[int, int]] = {}
        consecutive_errors = 0
        # While the meter is down (or not reached yet since setup), one failed read
        # ends the attempt, so a dead meter costs one timeout per retry instead of
        # one per read, and HA startup isn't held up.
        if self._failed_polls or not self._has_connected:
            max_errors = 1
        else:
            max_errors = MAX_CONSECUTIVE_READ_ERRORS

        pending = list(self._blocks)
        while pending:
            block = pending.pop(0)
            try:
                result = await self.client.read_input_registers(
                    address=block.start,
                    count=block.count,
                    device_id=self.slave_id,
                )
            except (ModbusException, asyncio.TimeoutError, OSError) as err:
                consecutive_errors += 1
                _LOGGER.debug("Modbus error reading address %s: %s", block.start, err)
                # Reconnect to clear transaction ID mismatches / half-open sockets
                self._close_client()
                if consecutive_errors >= max_errors:
                    raise MeterUnavailable(
                        f"No response from SDM630 slave {self.slave_id}: {err}"
                    ) from err
                await asyncio.sleep(0.5)
                if not await self._async_connect():
                    raise MeterUnavailable(f"Cannot reconnect to {self.client}") from err
                # Retry the same block; a second failure in a row ends the poll
                pending.insert(0, block)
                continue

            if result.isError():
                code = getattr(result, "exception_code", None)
                if code in _GATEWAY_NO_RESPONSE_CODES:
                    consecutive_errors += 1
                    _LOGGER.debug("Gateway reports no response at %s: %s", block.start, result)
                    if consecutive_errors >= max_errors:
                        raise MeterUnavailable(
                            f"Gateway gets no response from SDM630 slave {self.slave_id}"
                        )
                elif code in _ILLEGAL_RANGE_CODES and len(block.keys) > 1:
                    # The range spans registers this meter doesn't have: read the
                    # values individually from now on, starting right away
                    pending[0:0] = self._split_block(block)
                else:
                    # The meter answered but rejected this register (e.g. not on this model)
                    _LOGGER.debug("Read error at %s: %s", block.start, result)
                continue

            consecutive_errors = 0
            registers = result.registers
            for key, offset in block.keys:
                if offset + 1 < len(registers):
                    raw[key] = (registers[offset], registers[offset + 1])
            # Small delay between requests to allow gateway buffer to clear
            await asyncio.sleep(0.1)

        new_data = self._decode(raw)
        if not new_data:
            raise MeterUnavailable(f"SDM630 slave {self.slave_id} returned no data")
        return new_data

    def _decode(self, raw: dict[str, tuple[int, int]]) -> dict:
        """Turn register pairs into rounded values (None for NaN)."""
        values: dict[str, float | None] = {}
        auto_keys = []
        for key, (reg1, reg2) in raw.items():
            order = self.register_map[key].get("word_order", "AB")
            if order == "AB":
                values[key] = _decode_float(reg1, reg2)
            elif order == "BA":
                values[key] = _decode_float(reg2, reg1)
            elif order == "auto":
                auto_keys.append(key)
            else:
                raise ValueError(f"Unknown word_order '{order}' for {key}")

        for key in auto_keys:
            values[key] = self._decode_auto(key, raw[key], values)

        data = {}
        for key, value in values.items():
            if value is None or math.isnan(value):
                data[key] = None
            else:
                data[key] = round(value, self.register_map[key].get("precision", 2))
        return data

    def _decode_auto(self, key: str, regs: tuple[int, int], values: dict) -> float:
        """Pick the word order whose value matches the sum of related registers."""
        normal = _decode_float(regs[0], regs[1])
        swapped = _decode_float(regs[1], regs[0])
        parts = [values.get(part) for part in self.register_map[key].get("check_sum_of", ())]
        if not parts or any(part is None or math.isnan(part) for part in parts):
            return normal  # nothing to compare with: trust the documented order
        expected = sum(parts)

        def distance(value: float) -> float:
            return math.inf if math.isnan(value) else abs(value - expected)

        if distance(swapped) < distance(normal):
            _LOGGER.debug("%s: using swapped word order (%s vs %s)", key, swapped, normal)
            return swapped
        return normal
