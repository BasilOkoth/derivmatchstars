"""
Attended REAL one-contract execution using the SAME DigitMatchStar strategy
state as DEMO.

The strategy engine owns:
- V1 ranking
- candidate target
- current stake
- current/next trade number
- next-tick WIN/LOSS decision
- multiplier progression
- max-trades stop
- settlement reconciliation

This module only authorizes and submits one REAL purchase at a time. It does
not run a separate REAL strategy.
"""
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .db import SessionLocal
from .models import TradingSession, TradeLog
from .security import current_user_id
from .engine import engine

router = APIRouter(prefix="/real-manual", tags=["REAL strategy parity"])


def utcnow():
    return datetime.now(timezone.utc)


def utc_string(dt):
    return dt.isoformat()


def real_session(db, user_id, sid):
    s = db.get(TradingSession, sid)
    if s is None or str(s.user_id) != str(user_id):
        raise HTTPException(404, "Session not found")
    if str(s.account_mode).upper() != "REAL":
        raise HTTPException(409, "Requires a REAL account session")
    return s


def pending(s):
    try:
        value = json.loads(s.pending_trade_json or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def canonical_next_trade(s):
    return int(s.current_trade or 0) + 1


class QuoteRequest(BaseModel):
    # Optional compatibility checks only. The server engine is authoritative.
    digit: int | None = Field(default=None, ge=0, le=9)
    stake: float | None = Field(default=None, gt=0)


class ConfirmRequest(BaseModel):
    confirmation_token: str = Field(min_length=20)
    confirm: bool = Field(description="Must be true for this individual purchase")


@router.post("/sessions/{sid}/quote")
async def quote(
    sid: int,
    body: QuoteRequest,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()
    try:
        s = real_session(db, user_id, sid)

        if s.open_contract_id:
            active = engine.fast_contracts.get(int(s.id)) or {}
            # An older contract that has already had its local decision may
            # still be settling in the background, just like DEMO.
            if not active or not bool(active.get("decided")):
                raise HTTPException(
                    409,
                    "Current REAL contract has not had its next-tick decision yet",
                )

        if s.running:
            raise HTTPException(
                409,
                "REAL strategy is currently waiting for the active contract tick",
            )

        if not bool(s.pending_real_confirmation) or str(s.phase) not in {
            "REAL_TRADE_READY",
            "REAL_NEXT_TRADE_READY",
        }:
            raise HTTPException(
                409,
                f"REAL strategy is not ready for the next purchase (phase {s.phase})",
            )

        if int(s.current_trade or 0) >= int(s.max_trades or 0):
            raise HTTPException(409, "Max Trades reached")

        old = pending(s)
        if old.get("kind") in {"REAL_BUY_CLAIM", "REAL_BUY_UNCERTAIN"}:
            raise HTTPException(
                409,
                "Existing REAL purchase requires reconciliation",
            )

        # Canonical server feed/ranking must be live.
        tick = (getattr(engine, "latest_ticks", {}) or {}).get(s.id) or {}
        tick_epoch = int(tick.get("epoch") or 0)
        if not tick_epoch or abs(time.time() - tick_epoch) > 15:
            raise HTTPException(409, "Server tick feed is stale; quote blocked")

        # Re-score NOW using the exact same engine used by DEMO. The resulting
        # target becomes the canonical REAL purchase target.
        top_digit, rank = engine._choose_scored_digit(
            int(s.id),
            lock_target=True,
        )
        if top_digit is None or not rank.get("ready"):
            raise HTTPException(409, "Server V1 ranking not ready")

        engine._set_live_next_target(int(s.id), int(top_digit))
        s.candidate_digit = int(top_digit)

        canonical_stake = round(float(s.current_stake), 2)
        next_trade_no = canonical_next_trade(s)

        # Browser values, if supplied, are assertions rather than instructions.
        if body.digit is not None and int(body.digit) != int(top_digit):
            raise HTTPException(
                409,
                f"Browser digit {body.digit} differs from canonical V1 #1 {top_digit}",
            )
        if (
            body.stake is not None
            and abs(round(float(body.stake), 2) - canonical_stake) > 0.005
        ):
            raise HTTPException(
                409,
                f"Browser stake {body.stake:.2f} differs from canonical stake {canonical_stake:.2f}",
            )

        maximum = float(os.environ.get("REAL_MANUAL_MAX_STAKE_USD", "1.00"))
        if canonical_stake > maximum:
            raise HTTPException(
                400,
                f"Canonical stake exceeds REAL_MANUAL_MAX_STAKE_USD ({maximum:.2f})",
            )

        client = await engine._client(s.user_id, s.account_id)
        payload = await engine._request_proposal_payload(
            client,
            symbol=s.symbol,
            digit=int(top_digit),
            stake=canonical_stake,
            trade_no=next_trade_no,
            currency=await engine._currency_for(db, s),
        )

        token = secrets.token_urlsafe(32)
        expires = utcnow() + timedelta(seconds=15)
        snapshot = {
            "kind": "REAL_QUOTE",
            "token": token,
            "expires_at": utc_string(expires),
            "symbol": str(s.symbol),
            "digit": int(top_digit),
            "stake": canonical_stake,
            "trade_no": next_trade_no,
            "proposal_id": payload["proposal_id"],
            "ask_price": float(payload["ask_price"]),
            "payout": payload.get("payout"),
            "account_id": str(s.account_id),
            "score_evidence": engine._trade_score_evidence(
                int(s.id),
                int(top_digit),
            ),
            "quoted_tick_seq": int(engine.tick_sequence.get(int(s.id), 0)),
            "quoted_tick_epoch": int(engine.latest_tick_epoch.get(int(s.id), 0) or 0),
            "engine_instance_id": engine.instance_id,
        }

        s.pending_trade_json = json.dumps(snapshot)
        s.phase = "REAL_QUOTED"
        s.updated_at = datetime.utcnow()
        db.commit()

        return {
            "session_id": sid,
            "symbol": s.symbol,
            "digit": int(top_digit),
            "stake": canonical_stake,
            "trade_no": next_trade_no,
            "max_trades": int(s.max_trades),
            "ask_price": snapshot["ask_price"],
            "account_id": s.account_id,
            "confirmation_token": token,
            "expires_at": snapshot["expires_at"],
            "strategy_source": "DigitMatchStar shared engine",
        }
    finally:
        db.close()


@router.post("/sessions/{sid}/confirm")
async def confirm(
    sid: int,
    body: ConfirmRequest,
    user_id: str = Depends(current_user_id),
):
    if body.confirm is not True:
        raise HTTPException(400, "Explicit confirmation required")

    db = SessionLocal()
    try:
        s = (
            db.query(TradingSession)
            .filter(TradingSession.id == sid)
            .with_for_update()
            .one_or_none()
        )
        if s is None or str(s.user_id) != str(user_id):
            raise HTTPException(404, "Session not found")
        if str(s.account_mode).upper() != "REAL":
            raise HTTPException(409, "Requires a REAL account session")
        if s.running:
            raise HTTPException(409, "Active REAL contract is still awaiting its strategy tick")

        old = pending(s)
        if old.get("kind") != "REAL_QUOTE" or not secrets.compare_digest(
            str(old.get("token", "")),
            body.confirmation_token,
        ):
            raise HTTPException(409, "Quote expired, unavailable, or already used")

        if utcnow() > datetime.fromisoformat(old["expires_at"]):
            raise HTTPException(409, "Quote expired; request a fresh quote")

        if str(s.account_id) != old["account_id"] or str(s.symbol) != old["symbol"]:
            raise HTTPException(409, "Session changed; request a fresh quote")

        expected_trade_no = canonical_next_trade(s)
        if int(old.get("trade_no") or 0) != expected_trade_no:
            raise HTTPException(409, "Trade sequence changed; request a fresh quote")

        if abs(float(s.current_stake) - float(old["stake"])) > 0.005:
            raise HTTPException(409, "Stake progression changed; request a fresh quote")

        # Prevent buying a stale rank snapshot. REAL and DEMO must use the same
        # current target semantics.
        latest_digit, latest_rank = engine._choose_scored_digit(
            int(s.id),
            lock_target=False,
        )
        if latest_digit is None or int(latest_digit) != int(old["digit"]):
            raise HTTPException(409, "V1 #1 changed; request a fresh quote")

        old.pop("token", None)
        old["kind"] = "REAL_BUY_CLAIM"
        old["claimed_at"] = utc_string(utcnow())
        old["buy_sent_after_seq"] = int(engine.tick_sequence.get(int(s.id), 0))
        old["buy_sent_after_epoch"] = int(
            engine.latest_tick_epoch.get(int(s.id), 0) or 0
        )

        s.pending_trade_json = json.dumps(old)
        s.phase = "REAL_BUY_CLAIMED"
        s.updated_at = datetime.utcnow()
        db.commit()

        try:
            client = await engine._client(s.user_id, s.account_id)
            response = await client.request({
                "buy": old["proposal_id"],
                "price": old["ask_price"],
            })
            bought = response.get("buy") or {}
            contract_id = bought.get("contract_id")
            if not contract_id:
                raise RuntimeError("Deriv did not return a contract ID")
        except Exception as exc:
            old["kind"] = "REAL_BUY_UNCERTAIN"
            old["error"] = str(exc)
            s.pending_trade_json = json.dumps(old)
            s.running = False
            s.phase = "REAL_BUY_UNCERTAIN_STOPPED"
            s.last_error = (
                "REAL purchase status uncertain; reconcile before any further order"
            )
            db.commit()
            raise HTTPException(
                502,
                "Purchase status uncertain; check Deriv before any further order",
            ) from exc

        # From this point forward the REAL contract enters the exact SAME
        # next-tick and settlement pipeline used by DEMO.
        contract_id = str(contract_id)
        buy_ack_seq = int(engine.tick_sequence.get(int(s.id), 0))
        buy_ack_epoch = int(engine.latest_tick_epoch.get(int(s.id), 0) or 0)
        purchase_epoch = int(
            bought.get("start_time")
            or bought.get("purchase_time")
            or buy_ack_epoch
            or 0
        )
        decision_after_epoch = max(buy_ack_epoch, purchase_epoch)

        # Retire the previous locally-decided owner, if its official settlement
        # is still arriving in the background.
        prior = engine.fast_contracts.get(int(s.id))
        if prior and bool(prior.get("decided")):
            prior_contract = str(prior.get("contract_id") or "")
            if prior_contract:
                engine.retired_fast_contracts[
                    (int(s.id), prior_contract)
                ] = dict(prior)
            engine.fast_contracts.pop(int(s.id), None)

        score_evidence = old.get("score_evidence") or engine._trade_score_evidence(
            int(s.id),
            int(old["digit"]),
        )

        db.add(
            TradeLog(
                user_id=s.user_id,
                trading_session_id=s.id,
                trade_no=int(old["trade_no"]),
                account_mode=s.account_mode,
                account_id=s.account_id,
                symbol=s.symbol,
                digit=int(old["digit"]),
                stake=float(old["stake"]),
                contract_id=contract_id,
                status="OPEN",
                buy_price=float(
                    bought.get("buy_price")
                    or old["ask_price"]
                ),
                payout=(
                    float(bought.get("payout"))
                    if bought.get("payout") is not None
                    else old.get("payout")
                ),
                raw_json=json.dumps({
                    "deriv_buy": response,
                    "dms_score_evidence": score_evidence,
                    "execution_integrity": {
                        "instance_id": engine.instance_id,
                        "execution_mode": "REAL_EXPLICIT_CONFIRM",
                        "claimed_trade_no": int(old["trade_no"]),
                        "buy_sent_after_seq": int(old["buy_sent_after_seq"]),
                        "buy_sent_after_epoch": int(old["buy_sent_after_epoch"]),
                        "buy_ack_seq": buy_ack_seq,
                        "buy_ack_epoch": buy_ack_epoch,
                        "inflight_tick_count": max(
                            0,
                            int(buy_ack_seq) - int(old["buy_sent_after_seq"]),
                        ),
                        "arming_policy": (
                            "OFFICIAL_ONLY_INFLIGHT_TICK"
                            if int(buy_ack_seq) > int(old["buy_sent_after_seq"])
                            else "FIRST_NEW_SERVER_TICK_AFTER_BUY_ACK"
                        ),
                    },
                }, default=str),
            )
        )

        inflight_tick_count = max(
            0,
            int(buy_ack_seq) - int(old["buy_sent_after_seq"]),
        )
        official_only_inflight = inflight_tick_count > 0

        execution_state = {
            "contract_id": contract_id,
            "target_digit": int(old["digit"]),
            "symbol": str(s.symbol),
            "trade_no": int(old["trade_no"]),
            "buy_sent_after_seq": int(old["buy_sent_after_seq"]),
            "buy_sent_after_epoch": int(old["buy_sent_after_epoch"]),
            "buy_ack_seq": int(buy_ack_seq),
            "buy_ack_epoch": int(buy_ack_epoch),
            "purchase_epoch": int(purchase_epoch or 0) or None,
            "inflight_tick_count": int(inflight_tick_count),
            "decision_mode": (
                "OFFICIAL_ONLY_INFLIGHT_TICK"
                if official_only_inflight
                else "FAST_NEXT_TICK"
            ),
            "decision_seq": None,
            "decision_epoch": None,
            "decision_digit": None,
            "local_result": None,
            "official_result": None,
            "decided": False,
        }
        engine.execution_contract_state[int(s.id)] = execution_state

        if official_only_inflight:
            engine.fast_contracts.pop(int(s.id), None)
        else:
            engine.fast_contracts[int(s.id)] = {
                "contract_id": contract_id,
                "target_digit": int(old["digit"]),
                "symbol": str(s.symbol),
                "trade_no": int(old["trade_no"]),
                "armed_after_epoch": decision_after_epoch,
                "armed_after_seq": buy_ack_seq,
                "buy_sent_after_seq": int(old["buy_sent_after_seq"]),
                "buy_ack_seq": buy_ack_seq,
                "score_evidence": score_evidence,
                "buy_claim_token": "REAL_EXPLICIT_CONFIRM",
                "instance_id": engine.instance_id,
                "decided": False,
            }

        snapshot = engine.digit_score_snapshots.get(int(s.id))
        if isinstance(snapshot, dict):
            snapshot["execution_contract"] = json.loads(
                json.dumps(execution_state)
            )

        s.open_contract_id = contract_id
        s.current_trade = int(old["trade_no"])
        s.candidate_digit = int(old["digit"])
        s.running = True
        s.paused = False
        s.pending_real_confirmation = False
        s.pending_trade_json = None
        s.phase = (
            "WAITING_OFFICIAL_SETTLEMENT_INFLIGHT_TICK"
            if official_only_inflight
            else "PIPELINE_ACTIVE"
        )
        s.last_error = None
        s.updated_at = datetime.utcnow()
        db.commit()

        await engine._ensure_tick_subscription(
            sid=s.id,
            user_id=s.user_id,
            account_id=s.account_id,
            symbol=s.symbol,
            client=client,
        )

        # Settlement remains background-only, exactly as in DEMO.
        import asyncio
        asyncio.create_task(
            engine._subscribe_open_contract(
                sid=s.id,
                user_id=s.user_id,
                account_id=s.account_id,
                contract_id=contract_id,
                client=client,
            )
        )

        return {
            "ok": True,
            "contract_id": contract_id,
            "account_id": s.account_id,
            "stake": float(old["stake"]),
            "digit": int(old["digit"]),
            "trade_no": int(old["trade_no"]),
            "max_trades": int(s.max_trades),
            "phase": s.phase,
            "strategy_source": "DigitMatchStar shared engine",
        }
    finally:
        db.close()


@router.get("/sessions/{sid}/order")
async def order_status(
    sid: int,
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()
    try:
        s = real_session(db, user_id, sid)
        value = pending(s)
        fast = engine.fast_contracts.get(int(s.id)) or {}
        return {
            "phase": s.phase,
            "current_trade": int(s.current_trade or 0),
            "next_trade": int(s.current_trade or 0) + 1,
            "max_trades": int(s.max_trades or 0),
            "current_stake": float(s.current_stake or 0),
            "candidate_digit": s.candidate_digit,
            "pending_real_confirmation": bool(s.pending_real_confirmation),
            "open_contract_id": s.open_contract_id,
            "active_target": fast.get("target_digit"),
            "active_decided": fast.get("decided"),
            "pending_kind": value.get("kind"),
            "last_settlement": engine.last_settlement_status(int(s.id)),
        }
    finally:
        db.close()
