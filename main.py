from fastapi import FastAPI, HTTPException, Depends, Header, Request, status
from pydantic import BaseModel, Field
from typing import Dict, Any, AsyncGenerator
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from supabase import create_client, Client
import stripe
import secrets

# --- CONFIGURATIE ---
# Voor deze eerste onlinetest zijn dit dummy-waarden. 
# De try-except voorkomt dat de server crasht als je Supabase nog niet hebt ingericht.
SUPABASE_URL = "https://supabase.co"  
SUPABASE_KEY = "your-service-role-key"      
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- GLOBAL IN-MEMORY CACHE & DEVELOPER OVERRIDE ---
GLOBAL_MARKET_CACHE = {
    "epex_price": 0.05,        
    "onbalans_mode": "idle",   
    "last_updated": datetime.now(timezone.utc)
}

DEVELOPER_OVERRIDE = {
    "active": False,
    "epex_price": 0.05,
    "onbalans_mode": "idle"
}

# --- CONSTANTEN ---
EMS_AUTO = "Auto"
EMS_STANDBY = "Battery Standby"
INV_FORCE_CHARGE = "Force Charge"
INV_DISCHARGE = "General Mode"
DEFAULT_MAX_EXPORT = 16000

# --- BACKGROUND WORKER (Echte Marktdata) ---
async def fetch_market_data_periodically():
    while True:
        try:
            if not DEVELOPER_OVERRIDE["active"]:
                GLOBAL_MARKET_CACHE["epex_price"] = 0.08  
                GLOBAL_MARKET_CACHE["onbalans_mode"] = "idle"
                GLOBAL_MARKET_CACHE["last_updated"] = datetime.now(timezone.utc)
        except Exception as e:
            print(f"Fout bij ophalen marktdata: {e}")
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    bg_task = asyncio.create_task(fetch_market_data_periodically())
    yield
    bg_task.cancel()

app = FastAPI(title="EMS SaaS Cloud Platform - Testfase", version="3.2.0", lifespan=lifespan)

# --- PYDANTIC SCHEMAS ---
class InverterState(BaseModel):
    soc: float = Field(..., ge=0.0, le=100.0)
    pv_power: float = Field(..., ge=0.0)
    consumption: float = Field(..., ge=0.0)
    current_ems: str 
    current_inv: str 
    is_recovering: bool = Field(default=False)

class OptimizationResponse(BaseModel):
    license_active: bool
    change_ems_needed: bool
    target_ems_mode: str
    change_inv_needed: bool
    target_inverter_mode: str
    target_export_limit: int = Field(..., ge=0)
    is_recovering: bool

# --- DYNAMISCHE LICENTIE VERIFICATIE ---
async def verify_api_key_with_supabase(authorization: str = Header(...)) -> Dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Ongeldig token formaat")
    
    parts = authorization.split(" ")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Ongeldig token formaat")
    token = parts[1]
    
    # HARDCODED DEVELOPER BYPASS: Dit zorgt ervoor dat je direct online kunt testen!
    if token == "MIJN_EIGEN_HA_TEST_SLEUTEL":
        return {
            "license_active": True,
            "cfg_min_soc": 12.0,       
            "cfg_target_soc": 17.0,    
            "cfg_max_neg_price": -0.10,
            "cfg_max_export": DEFAULT_MAX_EXPORT,
            "cfg_headroom": 200
        }

    try:
        response = supabase.table("clients").select("*").eq("api_key", token).execute()
        records = response.data
        if not records or len(records) == 0:
            raise HTTPException(status_code=403, detail="Ongeldige API Key")
            
        client_data = records[0]
        return {
            "license_active": client_data.get("license_active", False),
            "cfg_min_soc": float(client_data.get("cfg_min_soc", 12.0)),       
            "cfg_target_soc": float(client_data.get("cfg_target_soc", 17.0)),    
            "cfg_max_neg_price": float(client_data.get("cfg_max_neg_price", -0.10)),
            "cfg_max_export": int(client_data.get("cfg_max_export", DEFAULT_MAX_EXPORT)),
            "cfg_headroom": int(client_data.get("cfg_headroom", 200))
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=403, detail="Database verificatie mislukt")

# --- ENGINE CORE LOGIC ---
def calculate_target_state(state: InverterState, market: Dict[str, Any], cfg: Dict[str, Any]) -> tuple:
    soc = state.soc
    min_soc = cfg["cfg_min_soc"]
    target_soc = cfg["cfg_target_soc"]
    
    if state.is_recovering:
        if soc < target_soc:
            return EMS_STANDBY, INV_FORCE_CHARGE, True
        current_recovering = False
    else:
        if soc <= min_soc:
            return EMS_STANDBY, INV_FORCE_CHARGE, True
        current_recovering = False

    is_deep_negative = market["epex_price"] <= cfg["cfg_max_neg_price"]
    is_grid_charging = market["onbalans_mode"] == "afregelen" or is_deep_negative
    is_grid_discharging = market["onbalans_mode"] == "opregelen"

    if is_grid_charging:
        return EMS_AUTO, INV_FORCE_CHARGE, current_recovering
    if is_grid_discharging:
        return EMS_AUTO, INV_DISCHARGE, current_recovering

    return EMS_AUTO, INV_DISCHARGE, current_recovering

# --- HOOFD ENDPOINT ---
@app.post("/v1/optimize", response_model=OptimizationResponse)
async def optimize_inverter(
    state: InverterState, 
    client: dict = Depends(verify_api_key_with_supabase)
):
    if not client["license_active"]:
        return OptimizationResponse(
            license_active=False, change_ems_needed=False, target_ems_mode=state.current_ems,
            change_inv_needed=False, target_inverter_mode=state.current_inv,
            target_export_limit=DEFAULT_MAX_EXPORT, is_recovering=False
        )

    market = DEVELOPER_OVERRIDE if DEVELOPER_OVERRIDE["active"] else GLOBAL_MARKET_CACHE
    target_ems_mode, target_inverter_mode, next_recovering_state = calculate_target_state(state, market, client)

    if market["epex_price"] <= client["cfg_max_neg_price"]:
        target_export_limit = int(max(0, state.consumption + client["cfg_headroom"]))
    else:
        target_export_limit = int(client["cfg_max_export"])

    return OptimizationResponse(
        license_active=True,
        change_ems_needed=state.current_ems != target_ems_mode,
        target_ems_mode=target_ems_mode,
        change_inv_needed=state.current_inv != target_inverter_mode,
        target_inverter_mode=target_inverter_mode,
        target_export_limit=target_export_limit,
        is_recovering=next_recovering_state
    )

# --- GEHEIM DEVELOPER TEST-ENDPOINT ---
@app.get("/dev/simulate")
async def simulate_market(price: float = 0.05, mode: str = "idle", reset: bool = False):
    if reset:
        DEVELOPER_OVERRIDE["active"] = False
        return {"status": "Reset naar echte live marktdata stream"}
    
    if mode not in ["idle", "afregelen", "opregelen"]:
        return {"error": "Mode moet zijn: idle, afregelen of opregelen"}
        
    DEVELOPER_OVERRIDE["active"] = True
    DEVELOPER_OVERRIDE["epex_price"] = price
    DEVELOPER_OVERRIDE["onbalans_mode"] = mode
    return {
        "status": "Simulator ACTIEF",
        "gesimuleerde_prijs": price,
        "gesimuleerde_onbalans": mode
    }
