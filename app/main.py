from datetime import datetime
from urllib.parse import urlparse

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
    version="3.0.0-digit-score-recycle3",
)


def _normalise_origin(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _cors_origins():
    """
    Allow the configured frontend plus the canonical DigitMatchStar domains.

    This prevents a www/non-www deployment mismatch from surfacing in the
    browser as the opaque JavaScript error: TypeError: Failed to fetch.
    """
    values = {
        _normalise_origin(settings.frontend_url),
        "https://digitmatchstar.com",
        "https://www.digitmatchstar.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    }

    configured = _normalise_origin(settings.frontend_url)

    # If FRONTEND_URL is a custom HTTPS hostname, also tolerate the www/non-www
    # spelling of that same hostname.
    if configured:
        try:
            parsed = urlparse(configured)
            if parsed.scheme in {"http", "https"} and parsed.hostname:
                host = parsed.hostname
                port = f":{parsed.port}" if parsed.port else ""

                if host.startswith("www."):
                    values.add(f"{parsed.scheme}://{host[4:]}{port}")
                else:
                    values.add(f"{parsed.scheme}://www.{host}{port}")
        except Exception:
            pass

    return sorted(x for x in values if x)


ALLOWED_ORIGINS = _cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
    max_trades: int = 15


class Candidate(BaseModel):
    digit: int


@app.on_event("startup")
async def startup():
    await engine.start()


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": "3.0.0-digit-score-recycle3",
        "frontend_origin": _normalise_origin(settings.frontend_url),
        "allowed_origins": ALLOWED_ORIGINS,
        "strategy": {
            "name": "DIGIT_SCORE_RECYCLE",
            "recycle_after_losses": int(
                getattr(getattr(engine, "digit_scorer", None), "recycle_after", 3)
            ),
        },
    }


def owns_session(db, user_id, sid):
    s = db.get(TradingSession, sid)

    if not s or s.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return s


def digit_score_for_session(session_id: int):
    """
    Compatibility wrapper around the new full engine.

    The replacement engine exposes _score_all_digits internally. Keeping the
    API adapter here avoids reintroducing old TAE methods into the engine.
    """
    scorer = getattr(engine, "_score_all_digits", None)

    if not callable(scorer):
        return {
            "ready": False,
            "ranking": [],
            "selected_digit": None,
            "history_count": 0,
            "minimum_history": 10,
            "recycle_after": 3,
            "error": "Digit score engine is not available",
        }

    try:
        return scorer(int(session_id))
    except Exception as exc:
        return {
            "ready": False,
            "ranking": [],
            "selected_digit": None,
            "history_count": 0,
            "minimum_history": 10,
            "recycle_after": int(
                getattr(getattr(engine, "digit_scorer", None), "recycle_after", 3)
            ),
            "error": str(exc),
        }


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
                    "digit_score": digit_score_for_session(s.id),
                    "recycle_after": int(
                        getattr(
                            getattr(engine, "digit_scorer", None),
                            "recycle_after",
                            3,
                        )
                    ),
                }
            )

        return result

    finally:
        db.close()


@app.get("/sessions/{sid}/tae/export")
def removed_tae_export(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    """
    Kept only so an old browser button does not crash the API.

    TAE no longer controls execution in the unified Digit Score / Recycle-3
    trading engine.
    """
    db = SessionLocal()
    try:
        owns_session(db, user_id, sid)
    finally:
        db.close()

    return {
        "schema": "DIGITMATCHSTAR_DIGIT_SCORE_RECYCLE3",
        "session_id": sid,
        "message": (
            "Target Attraction execution was retired. "
            "The active system scores digits 0-9 and recycles after 3 losses."
        ),
        "digit_score": digit_score_for_session(sid),
    }


@app.post("/sessions")
def create_session(
    body: SessionCreate,
    user_id: str = Depends(current_user_id),
):
    if body.base_stake <= 0:
        raise HTTPException(status_code=400, detail="base_stake must be > 0")

    if body.multiplier < 1:
        raise HTTPException(status_code=400, detail="multiplier must be >= 1")

    if body.max_trades < 1:
        raise HTTPException(status_code=400, detail="max_trades must be >= 1")

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
                "current_trade": s.current_trade,
                "max_trades": s.max_trades,
                "candidate_digit": s.candidate_digit,
            }

        if s.running:
            return {
                "id": s.id,
                "account_id": s.account_id,
                "account_mode": s.account_mode,
                "symbol": s.symbol,
                "phase": s.phase,
                "running": True,
                "already_running": True,
                "reconcile_required": False,
                "open_contract_id": None,
                "current_trade": s.current_trade,
                "max_trades": s.max_trades,
                "candidate_digit": s.candidate_digit,
            }

        s.account_mode = mode
        s.symbol = body.symbol
        s.base_stake = float(body.base_stake)
        s.current_stake = float(body.base_stake)
        s.multiplier = float(body.multiplier)
        s.max_trades = int(body.max_trades)

        s.current_trade = 0
        s.pnl = 0.0
        s.running = False
        s.paused = False
        s.pending_real_confirmation = False
        s.pending_trade_json = None
        s.last_error = None
        s.phase = "CONFIGURED"
        s.updated_at = datetime.utcnow()

        # Candidate may remain from a previous idle session, but Trade 1 will
        # be rescored by the server engine from canonical history.
        db.commit()
        db.refresh(s)

        return {
            "id": s.id,
            "account_id": s.account_id,
            "account_mode": s.account_mode,
            "symbol": s.symbol,
            "phase": s.phase,
            "reconcile_required": False,
            "current_trade": s.current_trade,
            "max_trades": s.max_trades,
            "candidate_digit": s.candidate_digit,
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

        if s.running:
            return {
                "ok": True,
                "id": s.id,
                "phase": s.phase,
                "already_running": True,
                "reconciling": bool(s.open_contract_id),
                "open_contract_id": s.open_contract_id,
                "candidate_digit": s.candidate_digit,
            }

        if s.open_contract_id:
            return {
                "ok": True,
                "session_id": s.id,
                "candidate_digit": s.candidate_digit,
                "reconcile_required": True,
            }

        # This sets the initial/fallback digit only. Once the server has enough
        # canonical history, the unified engine scores 0-9 and chooses Trade 1.
        s.candidate_digit = int(body.digit)
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

        # A fallback digit is still accepted so START never fails merely because
        # scoring history is warming. The engine replaces it with the ranked
        # candidate as soon as scoring is ready.
        if s.candidate_digit is None:
            s.candidate_digit = 5

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
            "candidate_digit": s.candidate_digit,
            "max_trades": s.max_trades,
            "recycle_after": int(
                getattr(getattr(engine, "digit_scorer", None), "recycle_after", 3)
            ),
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

    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )
