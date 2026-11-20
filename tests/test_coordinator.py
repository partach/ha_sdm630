"""Coordinator tests against a fake Modbus client (no network, no timing)."""

import importlib
import logging
import struct
from datetime import timedelta

import pytest
from pymodbus.exceptions import ModbusIOException

from custom_components.ha_sdm630 import coordinator as coord
from custom_components.ha_sdm630.const import (
    REGISTER_SETS,
    RUNTIME_RETRY_INTERVALS,
    STARTUP_RETRY_INTERVAL,
)
from custom_components.ha_sdm630.coordinator import HA_SDM630Coordinator, plan_reads


def words(value: float) -> list[int]:
    return list(struct.unpack(">HH", struct.pack(">f", value)))


class Response:
    def __init__(self, registers=None, exception_code=None):
        self.registers = registers or []
        self.exception_code = exception_code

    def isError(self):
        return self.exception_code is not None


class FakeClient:
    """Answers reads from a register dict; can be switched off or made picky."""

    def __init__(self, values: dict[int, float], swapped: frozenset[int] = frozenset()):
        self.regs: dict[int, int] = {}
        for addr, value in values.items():
            high, low = words(value)
            if addr in swapped:
                high, low = low, high
            self.regs[addr], self.regs[addr + 1] = high, low
        self.online = True
        self.reject_gaps = False  # answer 0x02 when a read spans unknown registers
        self.connected = False
        self.reads: list[tuple[int, int]] = []
        self.connects = 0

    async def connect(self):
        self.connects += 1
        self.connected = self.online
        return self.connected

    def close(self):
        self.connected = False

    async def read_input_registers(self, address, count, device_id):
        self.reads.append((address, count))
        if not self.online:
            raise ModbusIOException("No response received")
        span = range(address, address + count)
        if self.reject_gaps and any(addr not in self.regs for addr in span):
            return Response(exception_code=0x02)
        return Response([self.regs.get(addr, 0) for addr in span])


def basic_values(overrides: dict[int, float] | None = None) -> dict[int, float]:
    values = {info["address"]: 1.0 for info in REGISTER_SETS["basic"].values()}
    values.update(overrides or {})
    return values


def make(hass, client, register_set="basic", **kwargs) -> HA_SDM630Coordinator:
    return HA_SDM630Coordinator(
        hass, client, 1, REGISTER_SETS[register_set], timedelta(seconds=10), config_entry=None, **kwargs
    )


def test_plan_reads_batches_and_respects_limits():
    basic = REGISTER_SETS["basic"]
    assert [(b.start, b.count) for b in plan_reads(basic)] == [(0, 18), (52, 28), (342, 2)]
    # 4 registers per read and no gaps: the pre-0.3.5 behaviour
    assert len(plan_reads(basic, max_registers=4, max_gap=0)) == 10
    for register_set in REGISTER_SETS.values():
        blocks = plan_reads(register_set)
        assert all(block.count <= 40 for block in blocks)
        planned = {key for block in blocks for key, _ in block.keys}
        assert planned == set(register_set)


async def test_reads_values_and_applies_direction_correction(hass):
    client = FakeClient(basic_values({52: -2500.0, 72: 0.0, 74: 15422.1}))
    coordinator = make(hass, client, invert_power=True, swap_import_export=True)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data["total_system_power"] == 2500.0
    assert coordinator.data["import_energy"] == 15422.1
    assert coordinator.data["export_energy"] == 0.0
    assert len(client.reads) == 3


async def test_rejected_range_falls_back_to_single_reads(hass):
    client = FakeClient(basic_values({52: 42.0}))
    client.reject_gaps = True
    coordinator = make(hass, client)
    await coordinator.async_refresh()
    # Every value is still read, in the same poll
    assert coordinator.last_update_success
    assert set(coordinator.data) == set(REGISTER_SETS["basic"])
    assert coordinator.data["total_system_power"] == 42.0
    # The contiguous block 0-17 is fine; 52-79 and its gaps were split
    assert coordinator.read_requests == 1 + 6 + 1
    client.reads.clear()
    await coordinator.async_refresh()
    assert len(client.reads) == coordinator.read_requests


@pytest.mark.parametrize("swapped", [False, True])
async def test_total_var_word_order_is_detected(hass, swapped):
    values = {info["address"]: 1.0 for info in REGISTER_SETS["full"].values()}
    values.update({24: 100.0, 26: 200.0, 28: 300.0, 60: 600.0})
    client = FakeClient(values, swapped=frozenset({60}) if swapped else frozenset())
    coordinator = make(hass, client, register_set="full")
    await coordinator.async_refresh()
    assert coordinator.data["total_system_var"] == 600.0


async def test_startup_failure_retries_every_5_minutes(hass):
    client = FakeClient(basic_values())
    client.online = False
    coordinator = make(hass, client)
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.update_interval == STARTUP_RETRY_INTERVAL
    await coordinator.async_refresh()
    assert coordinator.update_interval == STARTUP_RETRY_INTERVAL

    client.online = True
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.update_interval == timedelta(seconds=10)


async def test_runtime_failure_backs_off_and_recovers(hass):
    client = FakeClient(basic_values())
    coordinator = make(hass, client)
    await coordinator.async_refresh()
    assert coordinator.last_update_success

    client.online = False
    client.close()
    seen = []
    for _ in range(len(RUNTIME_RETRY_INTERVALS) + 2):
        await coordinator.async_refresh()
        seen.append(coordinator.update_interval)
    assert not coordinator.last_update_success
    assert seen == [*RUNTIME_RETRY_INTERVALS, RUNTIME_RETRY_INTERVALS[-1], RUNTIME_RETRY_INTERVALS[-1]]

    client.online = True
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.update_interval == timedelta(seconds=10)


async def test_dead_meter_costs_one_read_per_attempt(hass):
    client = FakeClient(basic_values())
    coordinator = make(hass, client, register_set="full")
    await coordinator.async_refresh()
    assert coordinator.read_requests == 7

    client.online = False
    for _ in range(3):
        client.reads.clear()
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        # At most one read of the 7 (none once the connection itself fails)
        assert len(client.reads) <= 1


async def test_single_glitch_is_tolerated(hass):
    client = FakeClient(basic_values())
    coordinator = make(hass, client)
    await coordinator.async_refresh()

    original = client.read_input_registers
    failures = iter([True])

    async def glitch_once(address, count, device_id):
        if next(failures, False):
            raise ModbusIOException("transaction id mismatch")
        return await original(address, count, device_id)

    client.read_input_registers = glitch_once
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    # The failed block was retried, so no value is missing from this poll
    assert set(coordinator.data) == set(REGISTER_SETS["basic"])
    assert client.connects == 2  # reconnected once


async def test_gateway_no_response_counts_as_unavailable(hass):
    client = FakeClient(basic_values())

    async def gateway_timeout(address, count, device_id):
        client.reads.append((address, count))
        return Response(exception_code=0x0B)

    client.read_input_registers = gateway_timeout
    coordinator = make(hass, client)
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert len(client.reads) == 1


def test_pymodbus_log_level_respects_user_configuration():
    pymodbus_logger = logging.getLogger("pymodbus")
    saved = pymodbus_logger.level
    try:
        pymodbus_logger.setLevel(logging.DEBUG)  # e.g. set via logger: in configuration.yaml
        importlib.reload(coord)
        assert pymodbus_logger.level == logging.DEBUG

        pymodbus_logger.setLevel(logging.NOTSET)
        importlib.reload(coord)
        assert pymodbus_logger.level == logging.CRITICAL
    finally:
        pymodbus_logger.setLevel(saved)
