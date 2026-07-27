"""EMS SaaS Universele Client Custom Integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)
DOMAIN = "ems_saas"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EMS SaaS via de wizard UI."""
    _LOGGER.info("EMS SaaS Integratie succesvol opgestart.")
    
    # Hier dwingen we straks het universele script mee te installeren bij de klant
    return True
