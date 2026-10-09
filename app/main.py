from datetime import datetime
import json
from urllib.parse import urlparse

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .db import SessionLocal
from .models import TradingSession, DerivAccount, DerivCredential, TradeLog
from .security import current_user_id, decrypt_token
from .oauth import router as oauth_router
from .deriv_rest import get_accounts
from .engine import engine


app = FastAPI(
    title="DigitMatchStar Production OAuth Backend",
    version="3.8.1-canonical-rank-cache",
)


def _normalise_origin(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _cors_origins():
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
        "version": "3.8.1-canonical-rank-cache",
        "frontend_origin": _normalise_origin(settings.frontend_url),
        "allowed_origins": ALLOWED_ORIGINS,
        "strategy": {
            "name": "DIGIT_SCORE_V1_LIVE_RANK_RECOVERY",
            "recycle_after_losses": int(
                getattr(getattr(engine, "digit_scorer", None), "recycle_after", 1)
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
    READ ONLY.

    /sessions must never become a scoring event. The canonical Deriv tick
    handler is the only place that advances ranking.
    """
    sid = int(session_id)
    snapshot = (
        getattr(engine, "digit_score_snapshots", {}) or {}
    ).get(sid)

    if isinstance(snapshot, dict) and snapshot:
        return snapshot

    history = (
        getattr(engine, "digit_history", {}) or {}
    ).get(sid)

    return {
        "version": getattr(
            getattr(engine, "digit_scorer", None),
            "VERSION",
            "DIGIT_SCORE_V1_STABLE",
        ),
        "ready": False,
        "ranking": [],
        "selected_digit": None,
        "history_count": len(history) if history is not None else 0,
        "minimum_history": int(
            getattr(
                getattr(engine, "digit_scorer", None),
                "min_history",
                10,
            )
        ),
        "recycle_after": int(
            getattr(
                getattr(engine, "digit_scorer", None),
                "recycle_after",
                1,
            )
        ),
        "status": "WAITING_FOR_CANONICAL_SERVER_TICK",
    }


@app.post("/accounts/refresh-balances")
async def refresh_account_balances(
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()

    try:
        credential = (
            db.query(DerivCredential)
            .filter(DerivCredential.user_id == user_id)
            .first()
        )

        if not credential:
            raise HTTPException(
                status_code=401,
                detail="Deriv account is not connected",
            )

        if (
            credential.expires_at
            and credential.expires_at <= datetime.utcnow()
        ):
            raise HTTPException(
                status_code=401,
                detail="Deriv OAuth token expired; reconnect Deriv",
            )

        access_token = decrypt_token(
            credential.encrypted_access_token
        )

        payload = await get_accounts(access_token)
        accounts = payload.get("data", [])

        if isinstance(accounts, dict):
            accounts = [accounts]

        if not isinstance(accounts, list):
            accounts = []

        refreshed = []

        for account in accounts:
            if not account or not account.get("account_id"):
                continue

            account_id = str(account.get("account_id"))

            row = (
                db.query(DerivAccount)
                .filter(
                    DerivAccount.user_id == user_id,
                    DerivAccount.account_id == account_id,
                )
                .first()
            )

            if not row:
                row = DerivAccount(
                    user_id=user_id,
                    account_id=account_id,
                )
                db.add(row)

            balance = None

            if account.get("balance") is not None:
                try:
                    balance = float(account.get("balance"))
                except Exception:
                    balance = None

            row.account_type = str(
                account.get("account_type", "")
            ).lower()
            row.currency = account.get("currency")
            row.status = account.get("status")
            row.balance = balance
            row.raw_json = json.dumps(account)
            row.updated_at = datetime.utcnow()

            refreshed.append({
                "account_id": account_id,
                "account_type": row.account_type,
                "currency": row.currency,
                "status": row.status,
                "balance": row.balance,
            })

        db.commit()

        return {
            "ok": True,
            "refreshed_at": datetime.utcnow().isoformat(),
            "accounts": refreshed,
        }

    except HTTPException:
        raise

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"Could not refresh Deriv balances: {exc}",
        ) from exc

    finally:
        db.close()


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

            active = (
                getattr(engine, "fast_contracts", {}) or {}
            ).get(s.id) or {}

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
                    "live_next_target": engine.live_next_target.get(s.id),
                    "open_contract_id": s.open_contract_id,
                    "open_contract_target": active.get("target_digit"),
                    "pnl": s.pnl,
                    "pending_real_confirmation": s.pending_real_confirmation,
                    "last_error": s.last_error,
                    "digit_score": digit_score_for_session(s.id),
                    "rank_latency": (
                        getattr(engine, "rank_latency", {}) or {}
                    ).get(s.id),
                    "recycle_after": int(
                        getattr(
                            getattr(engine, "digit_scorer", None),
                            "recycle_after",
                            1,
                        )
                    ),
                    "last_settlement": engine.last_settlement_status(s.id),
                }
            )

        return result

    finally:
        db.close()


@app.get("/sessions/{sid}/trigger-fusion/export")
def export_trigger_fusion(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()

    try:
        session = owns_session(db, user_id, sid)

        rows = (
            db.query(TradeLog)
            .filter(
                TradeLog.user_id == user_id,
                TradeLog.trading_session_id == sid,
            )
            .order_by(TradeLog.id.asc())
            .all()
        )

        records = []

        for row in rows:
            try:
                raw = json.loads(row.raw_json or "{}")
                if not isinstance(raw, dict):
                    raw = {"raw": raw}
            except Exception:
                raw = {"raw_text": row.raw_json}

            evidence = raw.get("dms_score_evidence") or {}
            candidate = evidence.get("candidate") or {}
            shadow = evidence.get("shadow") or {}
            shadow_row = shadow.get("selected_row") or {}
            dominance = shadow.get("dominance") or {}
            signals = shadow_row.get("signals") or {}

            records.append({
                "trade_log_id": row.id,
                "session_id": row.trading_session_id,
                "trade_no": row.trade_no,
                "account_mode": row.account_mode,
                "account_id": row.account_id,
                "symbol": row.symbol,
                "target_digit": row.digit,
                "stake": row.stake,
                "contract_id": row.contract_id,
                "status": row.status,
                "buy_price": row.buy_price,
                "quoted_payout": row.payout,
                "settlement_profit": row.profit,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "settled_at": row.settled_at.isoformat() if row.settled_at else None,
                "score_version": evidence.get("score_version"),
                "history_count": evidence.get("history_count"),
                "selected_digit": evidence.get("selected_digit"),
                "executed_target": evidence.get("locked_target_digit", row.digit),
                "executed_v1_score": candidate.get("score"),
                "top_margin": evidence.get("top_margin"),
                "excluded_digit": evidence.get("excluded_digit"),
                "shadow_version": shadow.get("version"),
                "shadow_selected_digit": shadow.get("selected_digit"),
                "shadow_score": shadow_row.get("shadow_score"),
                "signal_agreement": shadow_row.get("signal_agreement"),
                "signal_total": shadow_row.get("signal_total"),
                "strength": shadow_row.get("strength"),
                "gap": candidate.get("gap"),
                "freq5": candidate.get("freq5"),
                "freq10": candidate.get("freq10"),
                "freq25": candidate.get("freq25"),
                "freq50": candidate.get("freq50"),
                "freq100": candidate.get("freq100"),
                "transition1": candidate.get("transition1"),
                "transition2": candidate.get("transition2"),
                "entropy10": candidate.get("entropy10"),
                "entropy25": candidate.get("entropy25"),
                "short_long_divergence": candidate.get("short_long_divergence"),
                "cluster_pressure": candidate.get("cluster_pressure"),
                "safe_tick_like": candidate.get("safe_tick_like"),
                "trend_velocity": shadow_row.get("trend_velocity"),
                "trend_blocks": shadow_row.get("trend_blocks"),
                "dominance_match": shadow_row.get("dominance_match"),
                "dominance_window": dominance.get("window"),
                "dominance_margin": dominance.get("dominance_margin"),
                "break_digit_match": shadow_row.get("break_digit_match"),
                "alternating_pair_match": shadow_row.get("alternating_pair_match"),
                "signal_transition1": signals.get("transition1_support"),
                "signal_transition2": signals.get("transition2_support"),
                "signal_velocity": signals.get("trend_velocity_positive"),
                "signal_recent_frequency": signals.get("recent_frequency_support"),
                "signal_dominance": signals.get("dominant_digit_support"),
                "signal_break_digit": signals.get("break_digit_support"),
                "signal_alternating_pair": signals.get("alternating_pair_support"),
                "dominant_digit": dominance.get("dominant_digit"),
                "dominant_frequency": dominance.get("dominant_frequency"),
                "second_frequency": dominance.get("second_frequency"),
                "least_frequency_digit": dominance.get("least_frequency_digit"),
                "least_frequency": dominance.get("least_frequency"),
                "evidence": evidence,
            })

        return {
            "schema": "DIGITMATCHSTAR_TRIGGER_FUSION_V2_EXPORT",
            "exported_at": datetime.utcnow().isoformat(),
            "session": {
                "id": session.id,
                "account_id": session.account_id,
                "account_mode": session.account_mode,
                "symbol": session.symbol,
            },
            "records": records,
        }

    finally:
        db.close()


@app.get("/sessions/{sid}/tae/export")
def removed_tae_export(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()
    try:
        owns_session(db, user_id, sid)
    finally:
        db.close()

    return {
        "schema": "DIGITMATCHSTAR_RERANK_EVERY_LOSS",
        "session_id": sid,
        "message": (
            "Target Attraction execution is retired. "
            "The active system ranks 0-9 and reranks after every loss."
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
            raise HTTPException(status_code=400, detail="Deriv account does not belong to this user")

        mode = "DEMO" if str(acct.account_type or "").lower() == "demo" else "REAL"

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
        raise HTTPException(status_code=400, detail="digit must be 0..9")

    db = SessionLocal()
    try:
        s = owns_session(db, user_id, sid)

        if s.running or s.open_contract_id:
            return {
                "ok": True,
                "session_id": s.id,
                "candidate_digit": s.candidate_digit,
                "reconcile_required": bool(s.open_contract_id),
                "already_running": bool(s.running),
            }

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
                getattr(getattr(engine, "digit_scorer", None), "recycle_after", 1)
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
        return {"ok": True, "phase": s.phase}
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
        s.phase = (
            "STOPPED_WAITING_SETTLEMENT"
            if s.open_contract_id
            else "STOPPED"
        )
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
        return {"ok": True, "session_id": sid}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc))
