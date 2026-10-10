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
    version="3.8.0-live-v1-target-tracking",
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
        "version": "3.8.0-live-v1-target-tracking",
        "frontend_origin": _normalise_origin(settings.frontend_url),
        "allowed_origins": ALLOWED_ORIGINS,
        "strategy": {
            "name": "DIGIT_SCORE_V1_LIVE_RANK_RECOVERY",
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



@app.post("/accounts/refresh-balances")
async def refresh_account_balances(
    user_id: str = Depends(current_user_id),
):
    """
    Pull the latest Options account balances from Deriv and persist them.

    Fixes stale balances after deposits/withdrawals. The Deriv OAuth token
    remains server-side and is never exposed to the browser.
    """
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
    """
    Export persisted DigitScore V2 Trigger Fusion evidence from TradeLog.

    Data comes from PostgreSQL/SQLAlchemy, not browser memory.
    """
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

            record = {
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

                # Ranking snapshot
                "score_version": evidence.get("score_version"),
                "history_count": evidence.get("history_count"),
                "selected_digit": evidence.get("selected_digit"),
                "executed_target": evidence.get("locked_target_digit", row.digit),
                "executed_v1_score": candidate.get("score"),
                "top_margin": evidence.get("top_margin"),
                "excluded_digit": evidence.get("excluded_digit"),

                # Shadow Trigger Fusion research — NEVER used for execution.
                "shadow_version": shadow.get("version"),
                "shadow_selected_digit": shadow.get("selected_digit"),
                "shadow_score": shadow_row.get("shadow_score"),
                "signal_agreement": shadow_row.get("signal_agreement"),
                "signal_total": shadow_row.get("signal_total"),
                "strength": shadow_row.get("strength"),

                # Compatibility fields
                "final_score": candidate.get("score"),
                "base_score": candidate.get("score"),
                "trigger_bonus": 0.0,

                # Core features
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

                # Trigger Fusion features
                "trend_velocity": shadow_row.get("trend_velocity"),
                "trend_blocks": shadow_row.get("trend_blocks"),
                "trend_bonus": None,
                "dominance_match": shadow_row.get("dominance_match"),
                "dominance_bonus": None,
                "dominance_window": dominance.get("window"),
                "dominance_margin": dominance.get("dominance_margin"),
                "break_digit_match": shadow_row.get("break_digit_match"),
                "break_digit_bonus": None,
                "alternating_pair_match": shadow_row.get("alternating_pair_match"),
                "alternating_pair_bonus": None,
                "digit9_setup": None,

                # Individual agreement signals
                "signal_transition1": signals.get("transition1_support"),
                "signal_transition2": signals.get("transition2_support"),
                "signal_velocity": signals.get("trend_velocity_positive"),
                "signal_recent_frequency": signals.get("recent_frequency_support"),
                "signal_dominance": signals.get("dominant_digit_support"),
                "signal_break_digit": signals.get("break_digit_support"),
                "signal_alternating_pair": signals.get("alternating_pair_support"),

                # Dominance snapshot
                "dominant_digit": dominance.get("dominant_digit"),
                "dominant_frequency": dominance.get("dominant_frequency"),
                "second_frequency": dominance.get("second_frequency"),
                "dominance_snapshot_margin": dominance.get("dominance_margin"),
                "least_frequency_digit": dominance.get("least_frequency_digit"),
                "least_frequency": dominance.get("least_frequency"),

                # Execution integrity
                "execution_instance_id": (
                    (raw.get("execution_integrity") or {}).get("instance_id")
                ),
                "buy_claim_token": (
                    (raw.get("execution_integrity") or {}).get("buy_claim_token")
                ),
                "execution_prearmed": (
                    (raw.get("execution_integrity") or {}).get("prearmed")
                ),

                # Raw evidence retained for full reproducibility
                "evidence": evidence,
            }

            records.append(record)

        # Derive cycle boundaries from trade-number reset. Consecutive
        # duplicate Trade 1 rows remain in the same derived cycle.
        cycle_index = 0
        previous_trade_no = None
        seen_by_cycle = {}

        for record in records:
            trade_no = int(record.get("trade_no") or 0)

            if cycle_index == 0:
                cycle_index = 1
            elif trade_no == 1 and previous_trade_no != 1:
                cycle_index += 1

            record["derived_cycle"] = cycle_index
            seen = seen_by_cycle.setdefault(cycle_index, set())
            record["duplicate_trade_in_cycle"] = trade_no in seen
            seen.add(trade_no)
            previous_trade_no = trade_no

        clean_records = [
            r for r in records
            if not r.get("duplicate_trade_in_cycle")
        ]
        duplicate_records = [
            r for r in records
            if r.get("duplicate_trade_in_cycle")
        ]

        settled = [r for r in records if r.get("status") == "SETTLED"]
        clean_settled = [
            r for r in clean_records
            if r.get("status") == "SETTLED"
        ]
        wins = [
            r for r in clean_settled
            if float(r.get("settlement_profit") or 0) > 0
        ]
        losses = [
            r for r in clean_settled
            if float(r.get("settlement_profit") or 0) <= 0
        ]

        total_profit = sum(
            float(r.get("settlement_profit") or 0)
            for r in clean_settled
        )

        return {
            "schema": "DIGITMATCHSTAR_TRIGGER_FUSION_V2_EXPORT",
            "score_version": getattr(
                getattr(engine, "digit_scorer", None),
                "VERSION",
                "DIGIT_SCORE_V2_TRIGGER_FUSION",
            ),
            "exported_at": datetime.utcnow().isoformat(),
            "session": {
                "id": session.id,
                "account_id": session.account_id,
                "account_mode": session.account_mode,
                "symbol": session.symbol,
            },
            "summary": {
                "records_count": len(records),
                "clean_records_count": len(clean_records),
                "duplicates_detected": len(duplicate_records),
                "settled_count": len(clean_settled),
                "wins": len(wins),
                "losses": len(losses),
                "settlement_net_pnl": total_profit,
            },
            "records": records,
            "clean_records": clean_records,
            "duplicate_records": duplicate_records,
        }

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
