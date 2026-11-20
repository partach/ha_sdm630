"""Test helpers."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.ha_sdm630.const import DOMAIN


async def add_tcp_meter(hass: HomeAssistant, port: int, slave: int = 1, name: str = "Heatpump", framer: str = "socket"):
    """Run the config flow for a TCP meter and return the last flow result."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"connection_type": "tcp"})
    assert result["step_id"] == "tcp"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": name, "host": "127.0.0.1", "port": port, "framer": framer, "slave_id": slave},
    )
    await hass.async_block_till_done()
    return result


async def set_options(hass: HomeAssistant, entry_id: str, **changes) -> None:
    """Submit the options form with defaults plus changes."""
    options = {
        "register_set": "basic",
        "update_interval": 10,
        "max_registers": 40,
        "invert_power": False,
        "swap_import_export": False,
        **changes,
    }
    result = await hass.config_entries.options.async_init(entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], options)
    await hass.async_block_till_done()
