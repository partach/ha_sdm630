"""Setup, register sets, shared connections and unload."""

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_sdm630.const import DOMAIN, STARTUP_RETRY_INTERVAL
from custom_components.ha_sdm630.hub import get_hubs

from .helpers import add_tcp_meter, set_options


def sensor_count(hass, entry) -> int:
    return len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))


async def test_sensors_names_and_units(hass, meter, caplog):
    caplog.set_level(logging.WARNING)
    await add_tcp_meter(hass, meter)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await set_options(hass, entry.entry_id, register_set="full")

    state = hass.states.get("sensor.heatpump_total_power")
    assert state.state == "-2500.0"
    assert state.attributes["friendly_name"] == "Heatpump Total Power"
    assert state.attributes["unit_of_measurement"] == "W"
    var = hass.states.get("sensor.heatpump_total_system_var")
    assert var.attributes["unit_of_measurement"] == "var"
    # Stored with swapped words by the simulated meter, decoded correctly
    assert var.state == "600.0"
    assert not [r for r in caplog.records if "unit" in r.getMessage().lower()]


async def test_smaller_register_set_removes_leftover_sensors(hass, meter):
    await add_tcp_meter(hass, meter)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    basic = sensor_count(hass, entry)
    await set_options(hass, entry.entry_id, register_set="full")
    assert sensor_count(hass, entry) > basic
    await set_options(hass, entry.entry_id, register_set="basic")
    assert sensor_count(hass, entry) == basic


async def test_meter_that_rejects_gaps_still_reads_everything(hass, start_meter):
    port = start_meter(mode="sparse")
    await add_tcp_meter(hass, port)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await set_options(hass, entry.entry_id, register_set="full")
    states = [s for s in hass.states.async_all("sensor") if s.entity_id.startswith("sensor.heatpump_")]
    assert len(states) == sensor_count(hass, entry)
    assert all(s.state not in ("unavailable", "unknown") for s in states)
    assert hass.states.get("sensor.heatpump_total_system_var").state == "600.0"


async def test_meters_on_one_gateway_share_the_connection(hass, meter):
    await add_tcp_meter(hass, meter, slave=1, name="Heatpump")
    await add_tcp_meter(hass, meter, slave=2, name="Garage")
    hubs = get_hubs(hass)
    assert len(hubs) == 1
    assert len(next(iter(hubs.values())).users) == 2

    first, second = hass.config_entries.async_entries(DOMAIN)
    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()
    assert len(hubs) == 1
    assert hass.states.get("sensor.garage_total_power").state == "-2500.0"

    await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert hubs == {}


async def test_unreachable_meter_at_startup_still_loads(hass, free_port):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heatpump",
        data={"connection_type": "tcp", "name": "Heatpump", "host": "127.0.0.1", "port": free_port, "slave_id": 1},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.heatpump_total_power").state == "unavailable"
    assert entry.runtime_data.update_interval == STARTUP_RETRY_INTERVAL
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
