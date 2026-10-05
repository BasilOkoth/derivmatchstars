from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from .engine import engine
from .db import SessionLocal
from .models import SessionState

app = FastAPI(title="DigitMatchStar Server Execution Engine")

class SessionConfig(BaseModel):
    account_mode: str = "DEMO"
    symbol: str = "R_10"
    base_stake: float = 1.0
    multiplier: float = 1.15
    max_trades: int = 10

class Candidate(BaseModel):
    digit: int

@app.on_event("startup")
async def startup():
    await engine.start()

def state_dict(s):
    return {
        "account_mode": s.account_mode,
        "symbol": s.symbol,
        "running": s.running,
        "paused": s.paused,
        "phase": s.phase,
        "base_stake": s.base_stake,
        "multiplier": s.multiplier,
        "max_trades": s.max_trades,
        "current_trade": s.current_trade,
        "current_stake": s.current_stake,
        "candidate_digit": s.candidate_digit,
        "open_contract_id": s.open_contract_id,
        "pending_real_confirmation": s.pending_real_confirmation,
        "pnl": s.pnl,
        "last_error": s.last_error,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/state")
def state():
    db = SessionLocal()
    try:
        s = db.get(SessionState, 1)
        if not s:
            s = SessionState(id=1)
            db.add(s); db.commit(); db.refresh(s)
        return state_dict(s)
    finally:
        db.close()

@app.post("/configure")
def configure(cfg: SessionConfig):
    mode = cfg.account_mode.upper()
    if mode not in ("DEMO", "REAL"):
        raise HTTPException(400, "account_mode must be DEMO or REAL")
    db = SessionLocal()
    try:
        s = db.get(SessionState, 1) or SessionState(id=1)
        if s.running or s.open_contract_id:
            raise HTTPException(409, "Stop/reconcile the current session before reconfiguring")
        s.account_mode = mode
        s.symbol = cfg.symbol
        s.base_stake = cfg.base_stake
        s.current_stake = cfg.base_stake
        s.multiplier = cfg.multiplier
        s.max_trades = cfg.max_trades
        s.current_trade = 0
        s.updated_at = datetime.utcnow()
        db.add(s); db.commit(); db.refresh(s)
        return state_dict(s)
    finally:
        db.close()

@app.post("/candidate")
def candidate(c: Candidate):
    if c.digit < 0 or c.digit > 9:
        raise HTTPException(400, "digit must be 0..9")
    db = SessionLocal()
    try:
        s = db.get(SessionState, 1)
        s.candidate_digit = c.digit
        s.updated_at = datetime.utcnow()
        db.commit()
        return state_dict(s)
    finally:
        db.close()

@app.post("/start")
def start():
    db = SessionLocal()
    try:
        s = db.get(SessionState, 1) or SessionState(id=1)
        s.running = True
        s.paused = False
        s.phase = "STARTING"
        s.updated_at = datetime.utcnow()
        db.add(s); db.commit(); db.refresh(s)
        return state_dict(s)
    finally:
        db.close()

@app.post("/pause")
def pause():
    db = SessionLocal()
    try:
        s = db.get(SessionState, 1)
        s.paused = True
        s.phase = "PAUSED"
        db.commit()
        return state_dict(s)
    finally:
        db.close()

@app.post("/stop")
def stop():
    db = SessionLocal()
    try:
        s = db.get(SessionState, 1)
        # Does not "cancel" an already purchased contract.
        # It stops any NEW purchase and lets reconcile_open_contract settle the current one.
        s.running = False
        s.paused = False
        s.phase = "STOPPED_WAITING_SETTLEMENT" if s.open_contract_id else "STOPPED"
        db.commit()
        return state_dict(s)
    finally:
        db.close()

@app.post("/real/confirm")
async def real_confirm():
    try:
        await engine.confirm_real_trade()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(409, str(e))
