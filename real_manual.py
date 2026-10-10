"""Explicitly confirmed REAL one-contract orders (not automated recovery).

Each purchase requires a fresh quote followed by a one-time confirmation.
A durable DB claim is committed before network purchase. Uncertain purchases
remain blocked until manually reconciled; there is deliberately no retry.
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .db import SessionLocal
from .models import TradingSession
from .security import current_user_id
from .engine import engine

router = APIRouter(prefix="/real-manual", tags=["REAL manual confirmation"])


def utcnow():
    return datetime.now(timezone.utc)


def utc_string(dt):
    return dt.isoformat()


def require_owner(db, user_id, sid):
    s = db.get(TradingSession, sid)
    if s is None or str(s.user_id) != str(user_id):
        raise HTTPException(404, "Session not found")
    if str(s.account_mode).upper() != "REAL":
        raise HTTPException(409, "Requires a REAL account session")
    if s.running or s.open_contract_id:
        raise HTTPException(409, "Stop the automated cycle before manual REAL orders")
    return s


def pending(s):
    try:
        return json.loads(s.pending_trade_json or "{}")
    except (ValueError, TypeError):
        return {}


class QuoteRequest(BaseModel):
    digit: int = Field(ge=0, le=9)
    stake: float = Field(gt=0)


class ConfirmRequest(BaseModel):
    confirmation_token: str = Field(min_length=20)
    confirm: bool = Field(description="Must be true for this individual purchase")


@router.post("/sessions/{sid}/quote")
async def quote(sid: int, body: QuoteRequest, user_id: str = Depends(current_user_id)):
    maximum = float(os.environ.get("REAL_MANUAL_MAX_STAKE_USD", "1.00"))
    if body.stake > maximum:
        raise HTTPException(400, f"Stake exceeds REAL_MANUAL_MAX_STAKE_USD ({maximum:.2f})")
    db = SessionLocal()
    try:
        s = require_owner(db, user_id, sid)
        old = pending(s)
        if old.get("kind") in {"REAL_BUY_CLAIM", "REAL_BUY_UNCERTAIN", "REAL_PURCHASED"}:
            raise HTTPException(409, "Existing REAL order requires settlement/reconciliation")
        client = await engine._client(s.user_id, s.account_id)
        payload = await engine._request_proposal_payload(
            client, symbol=s.symbol, digit=body.digit, stake=body.stake,
            trade_no=1, currency=await engine._currency_for(db, s),
        )
        token = secrets.token_urlsafe(32)
        expires = utcnow() + timedelta(seconds=30)
        snapshot = {
            "kind": "REAL_QUOTE", "token": token, "expires_at": utc_string(expires),
            "symbol": str(s.symbol), "digit": body.digit, "stake": body.stake,
            "proposal_id": payload["proposal_id"], "ask_price": float(payload["ask_price"]),
            "account_id": str(s.account_id),
        }
        s.pending_trade_json = json.dumps(snapshot)
        s.updated_at = datetime.utcnow()
        db.commit()
        return {"session_id": sid, "symbol": s.symbol, "digit": body.digit,
                "stake": body.stake, "ask_price": snapshot["ask_price"],
                "account_id": s.account_id, "confirmation_token": token,
                "expires_at": snapshot["expires_at"],
                "warning": "REAL funds will be spent only after confirm=true; each trade needs its own confirmation"}
    finally:
        db.close()


@router.post("/sessions/{sid}/confirm")
async def confirm(sid: int, body: ConfirmRequest, user_id: str = Depends(current_user_id)):
    if body.confirm is not True:
        raise HTTPException(400, "Explicit confirmation required")
    db = SessionLocal()
    try:
        # PostgreSQL row lock prevents two simultaneous requests consuming one token.
        s = (db.query(TradingSession).filter(TradingSession.id == sid).with_for_update().one_or_none())
        if s is None or str(s.user_id) != str(user_id):
            raise HTTPException(404, "Session not found")
        if str(s.account_mode).upper() != "REAL" or s.running or s.open_contract_id:
            raise HTTPException(409, "REAL account must be idle")
        old = pending(s)
        if old.get("kind") != "REAL_QUOTE" or not secrets.compare_digest(
            str(old.get("token", "")), body.confirmation_token
        ):
            raise HTTPException(409, "Quote expired, unavailable, or already used")
        if utcnow() > datetime.fromisoformat(old["expires_at"]):
            raise HTTPException(409, "Quote expired; request a fresh quote")
        if str(s.account_id) != old["account_id"] or str(s.symbol) != old["symbol"]:
            raise HTTPException(409, "Session changed; request a fresh quote")
        old.pop("token", None)
        old["kind"] = "REAL_BUY_CLAIM"
        old["claimed_at"] = utc_string(utcnow())
        s.pending_trade_json = json.dumps(old)
        s.phase = "REAL_BUY_CLAIMED"
        s.updated_at = datetime.utcnow()
        db.commit()  # claim persists BEFORE submitting any Deriv buy

        try:
            client = await engine._client(s.user_id, s.account_id)
            # An explicitly approved, single REAL purchase. Never auto-retry.
            response = await client.request({"buy": old["proposal_id"], "price": old["ask_price"]})
            bought = response.get("buy") or {}
            contract_id = bought.get("contract_id")
            if not contract_id:
                raise RuntimeError("Deriv did not return a contract ID")
        except Exception as exc:
            old["kind"] = "REAL_BUY_UNCERTAIN"
            old["error"] = str(exc)
            s.pending_trade_json = json.dumps(old)
            s.phase = "REAL_BUY_UNCERTAIN_STOPPED"
            db.commit()
            raise HTTPException(502, "Purchase status uncertain; check Deriv before any further order") from exc
        old["kind"] = "REAL_PURCHASED"
        old["contract_id"] = str(contract_id)
        old["purchase_response"] = bought
        s.pending_trade_json = json.dumps(old, default=str)
        s.phase = "REAL_PURCHASED_AWAITING_SETTLEMENT"
        db.commit()
        return {"ok": True, "contract_id": str(contract_id), "account_id": s.account_id,
                "stake": old["stake"], "digit": old["digit"], "note": "No further trade will execute automatically"}
    finally:
        db.close()


@router.get("/sessions/{sid}/order")
async def order_status(sid: int, user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        s = require_owner(db, user_id, sid)
        value = pending(s)
        public = {k: value.get(k) for k in ("kind", "contract_id", "stake", "digit", "claimed_at")}
        if value.get("kind") == "REAL_PURCHASED" and value.get("contract_id"):
            client = await engine._client(s.user_id, s.account_id)
            response = await client.contract_status(value["contract_id"])
            public["official_contract"] = response.get("proposal_open_contract") or {}
        return public
    finally:
        db.close()
