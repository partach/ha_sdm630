"""Config flow, reconfigure and options flow."""

from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_sdm630.const import DOMAIN

from .helpers import add_tcp_meter, set_options


async def start_reconfigure(hass, entry):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )


async def test_tcp_meter_is_created(hass, meter):
    result = await add_tcp_meter(hass, meter)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "connection_type": "tcp",
        "name": "Heatpump",
        "host": "127.0.0.1",
        "port": meter,
        "framer": "socket",
        "slave_id": 1,
    }
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == f"tcp_127.0.0.1:{meter}_1"


async def test_rtu_over_tcp(hass, start_meter):
    port = start_meter(framer="rtu")
    # Plain Modbus TCP doesn't understand an RTU converter...
    result = await add_tcp_meter(hass, port, framer="socket")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] in ("read_error", "cannot_connect")

    # ...switching the protocol in the same form works
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Heatpump", "host": "127.0.0.1", "port": port, "framer": "rtu", "slave_id": 1},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.states.get("sensor.heatpump_total_power").state == "-2500.0"


async def test_same_meter_twice_is_refused(hass, meter):
    await add_tcp_meter(hass, meter)
    result = await add_tcp_meter(hass, meter)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_unreachable_meter_shows_error(hass, free_port):
    result = await add_tcp_meter(hass, free_port)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_changes_connection(hass, start_meter):
    old_port, new_port = start_meter(), start_meter()
    await add_tcp_meter(hass, old_port)
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await start_reconfigure(hass, entry)
    assert result["step_id"] == "reconfigure_tcp"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "port": new_port, "framer": "socket", "slave_id": 3}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["port"] == new_port
    assert entry.data["slave_id"] == 3
    assert entry.data["name"] == "Heatpump"
    assert entry.unique_id == f"tcp_127.0.0.1:{new_port}_3"
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.heatpump_total_power").state == "-2500.0"


async def test_reconfigure_into_existing_meter_is_refused(hass, start_meter):
    port = start_meter()
    await add_tcp_meter(hass, port, slave=1, name="One")
    await add_tcp_meter(hass, port, slave=2, name="Two")
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == "Two")
    result = await start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "port": port, "framer": "socket", "slave_id": 1}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_serial_offers_current_settings(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heatpump",
        data={
            "connection_type": "serial",
            "name": "Heatpump",
            "serial_port": "/dev/ttyUSB_missing",
            "slave_id": 1,
            "baudrate": 9600,
            "parity": "N",
            "stopbits": 1,
            "bytesize": 8,
        },
    )
    entry.add_to_hass(hass)
    result = await start_reconfigure(hass, entry)
    assert result["step_id"] == "reconfigure_serial"
    schema = {str(key): key for key in result["data_schema"].schema}
    assert "name" not in schema
    assert schema["serial_port"].description["suggested_value"] == "/dev/ttyUSB_missing"
    # The port doesn't exist: the change is not saved
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"serial_port": "/dev/ttyUSB_other", "slave_id": 1, "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8},
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data["serial_port"] == "/dev/ttyUSB_missing"


async def test_options_invert_and_swap(hass, meter):
    await add_tcp_meter(hass, meter)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await set_options(hass, entry.entry_id, invert_power=True, swap_import_export=True)
    assert hass.states.get("sensor.heatpump_total_power").state == "2500.0"
    assert hass.states.get("sensor.heatpump_import_energy").state == "15422.1"
    assert hass.states.get("sensor.heatpump_export_energy").state == "0.0"
