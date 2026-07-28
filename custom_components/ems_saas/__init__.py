"""EMS SaaS Universele Client - Universeel EMS."""
import logging
import aiohttp
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)
DOMAIN = "ems_saas"

# Brand mapping: Cloud zegt altijd Force Charge / General Mode
# Wij vertalen naar merk-specifiek
BRAND_MAP = {
    "GoodWe": {
        "Force Charge": "eco_charge",
        "General Mode": "general",
        "entity": "select.goodwe_bedrijfsmodus_omvormer"
    },
    "SolaX Power": {
        "Force Charge": "Force Charge",
        "General Mode": "General Mode",
        "entity": "select.solax_inverter_operation_mode"
    },
    "Huawei SUN2000": {
        "Force Charge": "Forcible Charge",
        "General Mode": "Stop",
        "entity": "select.huawei_forced_charge_discharge"
    },
    "Victron Energy": {
        "Force Charge": "Keep Batteries Charged",
        "General Mode": "Optimized (with BatteryLife)",
        "entity": "select.victron_ess_mode"
    }
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info(f"EMS SaaS gestart voor merk: {entry.data.get('inverter_brand')}")

    api_key = entry.data.get("api_key")
    endpoint = entry.data.get("cloud_endpoint")
    brand = entry.data.get("inverter_brand", "GoodWe")

    # Jouw sensoren - voor nu hardcoded voor jouw GoodWe test
    # Later halen we deze uit de config_flow, net als merk
    SOC_ENTITY = "sensor.goodwe_battery_soc"
    PV_ENTITY = "sensor.goodwe_pv_power"
    CONSUMPTION_ENTITY = "sensor.goodwe_house_consumption"

    async def poll_cloud(now=None):
        try:
                SOC_ENTITY = "sensor.goodwe_battery_state_of_charge"
                PV_ENTITY = "sensor.goodwe_pv_power"
                CONSUMPTION_ENTITY = "sensor.goodwe_house_consumption"

            if not soc or not pv:
                return

            payload = {
                "soc": float(soc.state) if soc.state not in ('unknown','unavailable') else 0,
                "pv_power": float(pv.state) if pv.state not in ('unknown','unavailable') else 0,
                "consumption": float(con.state) if con and con.state not in ('unknown','unavailable') else 0,
                "current_ems": hass.states.get(BRAND_MAP[brand]["entity"]).state if hass.states.get(BRAND_MAP[brand]["entity"]) else "unknown",
                "current_inv": hass.states.get(BRAND_MAP[brand]["entity"]).state if hass.states.get(BRAND_MAP[brand]["entity"]) else "unknown",
                "is_recovering": False
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{endpoint}/v1/optimize", json=payload, headers=headers, timeout=15) as resp:
                    if resp.status!= 200:
                        _LOGGER.warning(f"EMS Cloud error: {resp.status}")
                        return
                    data = await resp.json()

                    if not data.get("license_active"):
                        return

                    if data.get("change_inv_needed"):
                        target_cloud = data.get("target_inverter_mode")
                        target_local = BRAND_MAP[brand].get(target_cloud, "general")

                        _LOGGER.info(f"EMS Cloud schakelt {brand} naar {target_local} (was {target_cloud})")

                        await hass.services.async_call(
                            "select", "select_option",
                            {"entity_id": BRAND_MAP[brand]["entity"], "option": target_local},
                            blocking=True
                        )

        except Exception as e:
            _LOGGER.error(f"EMS Poll error: {e}")

    # Elke 60 sec
    entry.async_on_unload(async_track_time_interval(hass, poll_cloud, timedelta(seconds=60)))
    # Direct 1x bij start
    await poll_cloud()

    return True
