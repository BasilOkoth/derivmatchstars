from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .db import SessionLocal
from .models import TradingSession, DerivAccount
from .security import current_user_id
from .oauth import router as oauth_router
from .engine import engine


app = FastAPI(
    title="DigitMatchStar Production OAuth Backend",
    version="2.1.8-target-attraction-export",
)

frontend_origin = settings.frontend_url.rstrip("/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

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
    return {
        "ok": True,
        "version": "2.1.8-target-attraction-export",
        "frontend_origin": frontend_origin,
    }


def owns_session(db, user_id, sid):
    s = db.get(TradingSession, sid)

    if not s or s.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return s


@app.get("/sessions")
def sessions(user_id: str = Depends(current_user_id)):
    db = SessionLocal()

    try:
        rows = (
            db.query(TradingSession)
            .filter(TradingSession.user_id == user_id)
            .all()
        )

        result = []

        for s in rows:
            acct = (
                db.query(DerivAccount)
                .filter(
                    DerivAccount.user_id == user_id,
                    DerivAccount.account_id == s.account_id,
                )
                .first()
            )

            result.append(
                {
                    "id": s.id,
                    "account_id": s.account_id,
                    "account_mode": s.account_mode,
                    "account_balance": acct.balance if acct else None,
                    "account_currency": acct.currency if acct else None,
                    "symbol": s.symbol,
                    "running": s.running,
                    "paused": s.paused,
                    "phase": s.phase,
                    "current_trade": s.current_trade,
                    "max_trades": s.max_trades,
                    "current_stake": s.current_stake,
                    "candidate_digit": s.candidate_digit,
                    "open_contract_id": s.open_contract_id,
                    "pnl": s.pnl,
                    "pending_real_confirmation": s.pending_real_confirmation,
                    "last_error": s.last_error,
                }
            )

        return result

    finally:
        db.close()


@app.get("/sessions/{sid}/tae/export")
def export_tae_results(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()
    try:
        owns_session(db, user_id, sid)
    finally:
        db.close()

    return engine.export_target_attraction(sid)


@app.post("/sessions")
def create_session(
    body: SessionCreate,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()

    try:
        acct = (
            db.query(DerivAccount)
            .filter(
                DerivAccount.user_id == user_id,
                DerivAccount.account_id == body.account_id,
            )
            .first()
        )

        if not acct:
            raise HTTPException(
                status_code=400,
                detail="Deriv account does not belong to this user",
            )

        account_type = str(acct.account_type or "").lower()
        mode = "DEMO" if account_type == "demo" else "REAL"

        s = (
            db.query(TradingSession)
            .filter(
                TradingSession.user_id == user_id,
                TradingSession.account_id == body.account_id,
            )
            .first()
        )

        if not s:
            s = TradingSession(
                user_id=user_id,
                account_id=body.account_id,
                account_mode=mode,
            )
            db.add(s)
            db.flush()

        if s.open_contract_id:
            s.running = False
            s.paused = False
            s.phase = "RECONCILE_REQUIRED"
            s.last_error = None
            s.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(s)

            return {
                "id": s.id,
                "account_id": s.account_id,
                "account_mode": s.account_mode,
                "symbol": s.symbol,
                "phase": s.phase,
                "reconcile_required": True,
                "open_contract_id": s.open_contract_id,
            }

        if s.running:
            raise HTTPException(
                status_code=409,
                detail="Session is already running",
            )

        s.account_mode = mode
        s.symbol = body.symbol
        s.base_stake = body.base_stake
        s.current_stake = body.base_stake
        s.multiplier = body.multiplier
        s.max_trades = body.max_trades

        s.current_trade = 0
        s.pnl = 0.0
        s.running = False
        s.paused = False
        s.pending_real_confirmation = False
        s.pending_trade_json = None
        s.last_error = None
        s.phase = "CONFIGURED"
        s.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(s)

        return {
            "id": s.id,
            "account_id": s.account_id,
            "account_mode": s.account_mode,
            "symbol": s.symbol,
            "phase": s.phase,
            "reconcile_required": False,
        }

    finally:
        db.close()


@app.post("/sessions/{sid}/candidate")
def candidate(
    sid: int,
    body: Candidate,
    user_id: str = Depends(current_user_id),
):
    if body.digit < 0 or body.digit > 9:
        raise HTTPException(
            status_code=400,
            detail="digit must be 0..9",
        )

    db = SessionLocal()

    try:
        s = owns_session(db, user_id, sid)

        if s.open_contract_id:
            return {
                "ok": True,
                "session_id": s.id,
                "candidate_digit": s.candidate_digit,
                "reconcile_required": True,
            }

        s.candidate_digit = body.digit
        s.updated_at = datetime.utcnow()

        db.commit()

        return {
            "ok": True,
            "session_id": s.id,
            "candidate_digit": s.candidate_digit,
            "reconcile_required": False,
        }

    finally:
        db.close()


@app.post("/sessions/{sid}/start")
def start(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()

    try:
        s = owns_session(db, user_id, sid)

        if s.open_contract_id:
            s.running = True
            s.paused = False
            s.phase = "RECONCILING"
            s.last_error = None
            s.updated_at = datetime.utcnow()

            db.commit()

            return {
                "ok": True,
                "id": s.id,
                "phase": s.phase,
                "reconciling": True,
                "open_contract_id": s.open_contract_id,
            }

        if s.candidate_digit is None:
            raise HTTPException(
                status_code=400,
                detail="Set a candidate digit before starting",
            )

        s.running = True
        s.paused = False
        s.phase = "STARTING"
        s.last_error = None
        s.updated_at = datetime.utcnow()

        db.commit()

        return {
            "ok": True,
            "id": s.id,
            "phase": s.phase,
            "reconciling": False,
        }

    finally:
        db.close()


@app.post("/sessions/{sid}/pause")
def pause(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()

    try:
        s = owns_session(db, user_id, sid)

        s.paused = True
        s.phase = "PAUSED"
        s.updated_at = datetime.utcnow()

        db.commit()

        return {
            "ok": True,
            "phase": s.phase,
        }

    finally:
        db.close()


@app.post("/sessions/{sid}/stop")
def stop(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()

    try:
        s = owns_session(db, user_id, sid)

        s.running = False
        s.paused = False

        if s.open_contract_id:
            s.phase = "STOPPED_WAITING_SETTLEMENT"
        else:
            s.phase = "STOPPED"

        s.updated_at = datetime.utcnow()

        db.commit()

        return {
            "ok": True,
            "phase": s.phase,
            "open_contract_id": s.open_contract_id,
        }

    finally:
        db.close()


@app.post("/sessions/{sid}/real/confirm")
async def confirm_real(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    try:
        await engine.confirm_real(user_id, sid)

        return {
            "ok": True,
            "session_id": sid,
        }

    except Exception as e:
        raise HTTPException(
            status_code=409,
            detail=str(e),
        )
