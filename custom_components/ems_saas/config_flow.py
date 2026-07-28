"""Config flow voor EMS SaaS Universele Client."""
from homeassistant import config_entries
import voluptuous as vol

DOMAIN = "ems_saas"

class EmsSaasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=f"EMS {user_input['inverter_brand']}", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_key"): str,
                vol.Required("cloud_endpoint", default="https://mijn-ems-backend.onrender.com"): str,
                vol.Required("inverter_brand", default="GoodWe"): vol.In(["GoodWe", "SolaX Power", "Huawei SUN2000", "Victron Energy"]),
            })
        )
