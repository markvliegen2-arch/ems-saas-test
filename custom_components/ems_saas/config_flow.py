"""Config flow voor EMS SaaS Universele Client."""
from homeassistant import config_entries
import voluptuous as vol

DOMAIN = "ems_saas"

class EmsSaasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Beheer de configuratieflow."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Eerste stap wanneer de klant de integratie inklikt."""
        if user_input is not None:
            return self.async_create_entry(title="EMS SaaS Cloud", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({})
        )
