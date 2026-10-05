import asyncio
import json
from datetime import datetime

from .config import settings
from .db import SessionLocal
from .models import TradingSession, DerivCredential, DerivAccount, TradeLog
from .security import decrypt_token
from .deriv_rest import get_ws_url
from .deriv_ws import DerivWS


class MultiUserEngine:
    def __init__(self):
        self.task = None
        self.clients = {}  # key=(user_id, account_id)

    async def start(self):
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_forever())

    async def _drop_client(self, user_id: str, account_id: str):
        key = (user_id, account_id)
        client = self.clients.pop(key, None)
        if client:
            try:
                await client.close()
            except Exception:
                pass

    async def _client(self, user_id: str, account_id: str):
        key = (user_id, account_id)
        client = self.clients.get(key)

        if client and client.is_open():
            return client

        if client:
            await self._drop_client(user_id, account_id)

        db = SessionLocal()
        try:
            cred = (
                db.query(DerivCredential)
                .filter(DerivCredential.user_id == user_id)
                .first()
            )

            if not cred:
                raise RuntimeError("AUTH: Deriv account is not connected")

            if cred.expires_at and cred.expires_at <= datetime.utcnow():
                raise RuntimeError(
                    "AUTH: Deriv OAuth access token expired; reconnect Deriv"
                )

            token = decrypt_token(cred.encrypted_access_token)
        finally:
            db.close()

        try:
            url = await get_ws_url(token, account_id)
        except Exception as exc:
            raise RuntimeError(f"OTP: {exc}") from exc

        client = DerivWS(url)

        try:
            await client.connect()
        except Exception as exc:
            raise RuntimeError(f"WEBSOCKET: {exc}") from exc

        self.clients[key] = client
        return client

    async def run_forever(self):
        while True:
            db = SessionLocal()
            try:
                ids = [
                    row.id
                    for row in (
                        db.query(TradingSession)
                        .filter(TradingSession.running == True)
                        .all()
                    )
                ]
            finally:
                db.close()

            for sid in ids:
                try:
                    await self.step(sid)
                except Exception as exc:
                    db = SessionLocal()
                    try:
                        s = db.get(TradingSession, sid)
                        if s:
                            # Stop the failed worker instead of hammering the same
                            # failing endpoint twice per second indefinitely.
                            s.running = False
                            s.paused = False
                            s.last_error = str(exc)
                            s.phase = "ERROR"
                            s.updated_at = datetime.utcnow()
                            db.commit()

                            await self._drop_client(s.user_id, s.account_id)
                    finally:
                        db.close()

            await asyncio.sleep(0.5)

    async def step(self, sid: int):
        db = SessionLocal()

        try:
            s = db.get(TradingSession, sid)

            if not s or not s.running or s.paused:
                return

            # Clear stale error once a fresh run actually enters the worker.
            if s.last_error:
                s.last_error = None
                db.commit()

            try:
                client = await self._client(s.user_id, s.account_id)
            except Exception as exc:
                raise RuntimeError(str(exc)) from exc

            if s.open_contract_id:
                s.phase = "WAITING_SETTLEMENT"
                db.commit()

                try:
                    data = await client.contract_status(s.open_contract_id)
                except Exception as exc:
                    raise RuntimeError(f"SETTLEMENT: {exc}") from exc

                poc = data.get("proposal_open_contract", {})

                if poc.get("is_sold"):
                    profit = float(poc.get("profit") or 0)
                    s.pnl += profit

                    log = (
                        db.query(TradeLog)
                        .filter(
                            TradeLog.trading_session_id == s.id,
                            TradeLog.contract_id == s.open_contract_id,
                        )
                        .order_by(TradeLog.id.desc())
                        .first()
                    )

                    if log:
                        log.status = "SETTLED"
                        log.profit = profit
                        log.settled_at = datetime.utcnow()
                        log.raw_json = json.dumps(data)

                    # Keep the server-side account balance snapshot current.
                    # Deriv's settled `profit` is net P/L for the contract, so
                    # adding it once at settlement tracks this bot's account change.
                    account = (
                        db.query(DerivAccount)
                        .filter(
                            DerivAccount.user_id == s.user_id,
                            DerivAccount.account_id == s.account_id,
                        )
                        .first()
                    )
                    if account and account.balance is not None:
                        account.balance = float(account.balance) + profit
                        account.updated_at = datetime.utcnow()

                    s.open_contract_id = None
                    s.pending_trade_json = None
                    s.pending_real_confirmation = False

                    if profit > 0:
                        # Cycle complete after a win.
                        s.current_stake = s.base_stake
                        s.phase = "WON"
                        s.running = False
                    else:
                        if s.current_trade >= s.max_trades:
                            s.phase = "MAX_TRADES_REACHED"
                            s.running = False
                        else:
                            # Keep the same frozen candidate digit for the
                            # already-started recovery cycle.
                            s.current_stake = round(
                                s.current_stake * s.multiplier, 2
                            )
                            s.phase = "RECOVERING"

                    s.updated_at = datetime.utcnow()
                    db.commit()

                return

            if s.pending_real_confirmation:
                s.phase = "WAITING_REAL_CONFIRMATION"
                db.commit()
                return

            if s.current_trade >= s.max_trades:
                s.running = False
                s.phase = "MAX_TRADES_REACHED"
                db.commit()
                return

            if s.candidate_digit is None:
                s.phase = "WAITING_CANDIDATE"
                db.commit()
                return

            account = (
                db.query(DerivAccount)
                .filter(
                    DerivAccount.user_id == s.user_id,
                    DerivAccount.account_id == s.account_id,
                )
                .first()
            )

            currency = (
                str(account.currency).upper()
                if account and account.currency
                else "USD"
            )

            s.phase = "REQUESTING_PROPOSAL"
            db.commit()

            try:
                proposal = await client.proposal_digitmatch(
                    symbol=s.symbol,
                    digit=s.candidate_digit,
                    amount=s.current_stake,
                    duration=1,
                    currency=currency,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"PROPOSAL [{s.symbol}/{currency}/digit {s.candidate_digit}]: {exc}"
                ) from exc

            p = proposal.get("proposal") or {}

            if not p.get("id"):
                raise RuntimeError(
                    f"PROPOSAL: Deriv returned no proposal id; keys={list(proposal.keys())}"
                )

            trade_payload = {
                "proposal_id": p["id"],
                "ask_price": float(p.get("ask_price") or s.current_stake),
                "payout": float(p.get("payout") or 0),
                "digit": s.candidate_digit,
                "stake": s.current_stake,
                "trade_no": s.current_trade + 1,
                "currency": currency,
            }

            if s.account_mode == "REAL":
                if not settings.allow_real_mode:
                    raise RuntimeError(
                        "REAL mode is disabled by server configuration"
                    )

                # Safety: real-money purchasing always requires explicit
                # confirmation for each purchase.
                s.pending_trade_json = json.dumps(trade_payload)
                s.pending_real_confirmation = True
                s.phase = "WAITING_REAL_CONFIRMATION"
                db.commit()
                return

            await self._execute_buy(db, s, client, trade_payload)

        finally:
            db.close()

    async def _execute_buy(self, db, s, client, payload):
        s.phase = "BUYING"
        db.commit()

        try:
            result = await client.buy(
                payload["proposal_id"],
                payload["ask_price"],
            )
        except Exception as exc:
            raise RuntimeError(f"BUY: {exc}") from exc

        buy = result.get("buy") or {}

        if not buy.get("contract_id"):
            raise RuntimeError(
                f"BUY: Deriv returned no contract_id; keys={list(result.keys())}"
            )

        contract_id = str(buy["contract_id"])

        db.add(
            TradeLog(
                user_id=s.user_id,
                trading_session_id=s.id,
                trade_no=payload["trade_no"],
                account_mode=s.account_mode,
                account_id=s.account_id,
                symbol=s.symbol,
                digit=payload["digit"],
                stake=payload["stake"],
                contract_id=contract_id,
                status="OPEN",
                buy_price=float(
                    buy.get("buy_price") or payload["ask_price"]
                ),
                payout=payload["payout"],
                raw_json=json.dumps(result),
            )
        )

        s.open_contract_id = contract_id
        s.phase = "WAITING_SETTLEMENT"
        s.current_trade += 1
        s.pending_trade_json = None
        s.pending_real_confirmation = False
        s.last_error = None
        s.updated_at = datetime.utcnow()

        db.commit()

    async def confirm_real(self, user_id: str, session_id: int):
        db = SessionLocal()

        try:
            s = db.get(TradingSession, session_id)

            if not s or s.user_id != user_id:
                raise RuntimeError("Session not found")

            if s.account_mode != "REAL":
                raise RuntimeError("Not a REAL session")

            if not s.pending_real_confirmation or not s.pending_trade_json:
                raise RuntimeError("No REAL trade awaiting confirmation")

            client = await self._client(s.user_id, s.account_id)
            payload = json.loads(s.pending_trade_json)

            # The proposal is intentionally generated before confirmation in
            # this build. If Deriv rejects it as stale, the dashboard exposes
            # that exact error and the user must start a fresh confirmed trade.
            await self._execute_buy(db, s, client, payload)

        finally:
            db.close()


engine = MultiUserEngine()
