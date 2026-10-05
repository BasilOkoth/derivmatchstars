from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from .db import SessionLocal
from .models import TradingSession, DerivAccount
from .security import current_user_id
from .oauth import router as oauth_router
from .engine import engine

app = FastAPI(title="DigitMatchStar Production OAuth Backend", version="2.0")
app.include_router(oauth_router)

class SessionCreate(BaseModel):
    account_id: str
    symbol: str = "R_10"
    base_stake: float = 1.0
    multiplier: float = 1.15
    max_trades: int = 10

class Candidate(BaseModel):
    digit: int

@app.on_event("startup")
async def startup():
    await engine.start()

@app.get("/health")
def health():
    return {"ok": True, "version": "2.0-oauth-multiuser"}

def owns_session(db, user_id, sid):
    s = db.get(TradingSession, sid)
    if not s or s.user_id != user_id:
        raise HTTPException(404, "Session not found")
    return s

@app.get("/sessions")
def sessions(user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        rows = db.query(TradingSession).filter(TradingSession.user_id == user_id).all()
        return [{
            "id": s.id, "account_id": s.account_id, "account_mode": s.account_mode,
            "symbol": s.symbol, "running": s.running, "paused": s.paused,
            "phase": s.phase, "current_trade": s.current_trade,
            "current_stake": s.current_stake, "candidate_digit": s.candidate_digit,
            "open_contract_id": s.open_contract_id, "pnl": s.pnl,
            "pending_real_confirmation": s.pending_real_confirmation,
            "last_error": s.last_error,
        } for s in rows]
    finally:
        db.close()

@app.post("/sessions")
def create_session(body: SessionCreate, user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        acct = db.query(DerivAccount).filter(
            DerivAccount.user_id == user_id,
            DerivAccount.account_id == body.account_id
        ).first()
        if not acct:
            raise HTTPException(400, "Deriv account does not belong to this user")
        mode = "DEMO" if acct.account_type.lower() == "demo" else "REAL"
        s = db.query(TradingSession).filter(
            TradingSession.user_id == user_id,
            TradingSession.account_id == body.account_id
        ).first()
        if not s:
            s = TradingSession(
                user_id=user_id, account_id=body.account_id, account_mode=mode
            )
            db.add(s)
        if s.running or s.open_contract_id:
            raise HTTPException(409, "Stop/reconcile current session before reconfiguration")
        s.symbol = body.symbol
        s.base_stake = body.base_stake
        s.current_stake = body.base_stake
        s.multiplier = body.multiplier
        s.max_trades = body.max_trades
        s.current_trade = 0
        s.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(s)
        return {"id": s.id, "account_id": s.account_id, "account_mode": s.account_mode}
    finally:
        db.close()

@app.post("/sessions/{sid}/candidate")
def candidate(sid: int, body: Candidate, user_id: str = Depends(current_user_id)):
    if body.digit < 0 or body.digit > 9:
        raise HTTPException(400, "digit must be 0..9")
    db = SessionLocal()
    try:
        s = owns_session(db, user_id, sid)
        s.candidate_digit = body.digit
        s.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.post("/sessions/{sid}/start")
def start(sid: int, user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        s = owns_session(db, user_id, sid)
        s.running = True
        s.paused = False
        s.phase = "STARTING"
        s.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "phase": s.phase}
    finally:
        db.close()

@app.post("/sessions/{sid}/pause")
def pause(sid: int, user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        s = owns_session(db, user_id, sid)
        s.paused = True
        s.phase = "PAUSED"
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.post("/sessions/{sid}/stop")
def stop(sid: int, user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        s = owns_session(db, user_id, sid)
        s.running = False
        s.paused = False
        s.phase = "STOPPED_WAITING_SETTLEMENT" if s.open_contract_id else "STOPPED"
        db.commit()
        return {"ok": True, "phase": s.phase}
    finally:
        db.close()

@app.post("/sessions/{sid}/real/confirm")
async def confirm_real(sid: int, user_id: str = Depends(current_user_id)):
    try:
        await engine.confirm_real(user_id, sid)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(409, str(e))
