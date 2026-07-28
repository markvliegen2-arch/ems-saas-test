import os, asyncio
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict
from datetime import datetime, timezone
from contextlib import asynccontextmanager

# 1 API KEY UIT ENV VAR - GEEN SUPABASE
VALID_API_KEY = os.getenv("API_KEY", "test_12345_mark")

GLOBAL_MARKET_CACHE = {"epex_price": -0.12, "onbalans_mode": "afregelen", "last_updated": datetime.now(timezone.utc)}
DEFAULT_MAX_EXPORT = 16000

EMS_AUTO = "Auto"
EMS_STANDBY = "Battery Standby"
INV_FORCE_CHARGE = "Force Charge"
INV_DISCHARGE = "General Mode"

async def fake_market_loop():
    while True:
        GLOBAL_MARKET_CACHE["last_updated"] = datetime.now(timezone.utc)
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(fake_market_loop())
    yield
    task.cancel()

app = FastAPI(title="EMS SaaS Cloud Test", version="4.0.0-test", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "ok", "version": "4.0.0-test", "market": GLOBAL_MARKET_CACHE}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/favicon.ico")
async def favicon():
    return {}

class InverterState(BaseModel):
    soc: float = Field(..., ge=0, le=100)
    pv_power: float = Field(..., ge=0)
    consumption: float = Field(..., ge=0)
    current_ems: str
    current_inv: str
    is_recovering: bool = False

class OptimizationResponse(BaseModel):
    license_active: bool
    change_ems_needed: bool
    target_ems_mode: str
    change_inv_needed: bool
    target_inverter_mode: str
    target_export_limit: int
    is_recovering: bool

async def verify_test_key(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Ongeldig token formaat")
    token = authorization.split(" ")[1]
    if token!= VALID_API_KEY:
        raise HTTPException(403, "Ongeldige API Key")
    # Hardcoded config voor je test huis
    return {"license_active": True, "cfg_min_soc": 12.0, "cfg_target_soc": 17.0, "cfg_max_neg_price": -0.10, "cfg_max_export": 16000, "cfg_headroom": 200}

def calculate_target_state(state: InverterState, market: Dict, cfg: Dict):
    if state.is_recovering:
        if state.soc < cfg["cfg_target_soc"]:
            return EMS_STANDBY, INV_FORCE_CHARGE, True
    else:
        if state.soc <= cfg["cfg_min_soc"]:
            return EMS_STANDBY, INV_FORCE_CHARGE, True
    if market["onbalans_mode"] == "afregelen" or market["epex_price"] <= cfg["cfg_max_neg_price"]:
        return EMS_AUTO, INV_FORCE_CHARGE, False
    return EMS_AUTO, INV_DISCHARGE, False

@app.post("/v1/optimize", response_model=OptimizationResponse)
async def optimize(state: InverterState, client: dict = Depends(verify_test_key)):
    t_ems, t_inv, t_rec = calculate_target_state(state, GLOBAL_MARKET_CACHE, client)
    limit = int(max(0, state.consumption + client["cfg_headroom"])) if GLOBAL_MARKET_CACHE["epex_price"] <= client["cfg_max_neg_price"] else int(client["cfg_max_export"])
    return OptimizationResponse(license_active=True, change_ems_needed=state.current_ems!=t_ems, target_ems_mode=t_ems, change_inv_needed=state.current_inv!=t_inv, target_inverter_mode=t_inv, target_export_limit=limit, is_recovering=t_rec)
