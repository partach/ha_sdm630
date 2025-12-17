from homeassistant.components import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.components import config_entries
import voluptuous as vol
from .const import CONF_REGISTER_SET, REGISTER_SET_BASIC, REGISTER_SET_BASIC_PLUS, REGISTER_SET_FULL, DEFAULT_REGISTER_SET

class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_REGISTER_SET,
                    default=self.config_entry.options.get(CONF_REGISTER_SET, DEFAULT_REGISTER_SET)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=REGISTER_SET_BASIC, label="Basic (fast, essential sensors)"),
                            selector.SelectOptionDict(value=REGISTER_SET_BASIC_PLUS, label="Basic+ (adds VA, power factor, neutral)"),
                            selector.SelectOptionDict(value=REGISTER_SET_FULL, label="Full (all 80+ registers – slower)"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            })
        )
