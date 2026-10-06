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
    """
    DEMO-only low-latency execution engine.

    V24 changes:
    - no foreground WAITING_SETTLEMENT polling
    - proposal_open_contract uses subscription callbacks
    - while Trade N is open, the engine prefetches the proposal for Trade N+1
    - on confirmed loss, it buys the prefetched recovery immediately
    - if the prefetched proposal is stale/rejected, it falls back to a fresh proposal
    - REAL automated purchases remain disabled
    """

    def __init__(self):
        self.task = None
        self.clients = {}
        self.contract_subscriptions = {}
        # Fallback settlement monitors used when Deriv returns no subscription id.
        self.contract_poll_tasks = {}
        self.session_tasks = {}
        self.session_locks = {}
        self.prefetched_recovery = {}  # sid -> payload

    async def start(self):
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_forever())

    def _lock(self, sid: int) -> asyncio.Lock:
        lock = self.session_locks.get(sid)
        if lock is None:
            lock = asyncio.Lock()
            self.session_locks[sid] = lock
        return lock

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
                task = self.session_tasks.get(sid)
                if not task or task.done():
                    self.session_tasks[sid] = asyncio.create_task(
                        self._safe_step(sid)
                    )

            await asyncio.sleep(0.02)

    async def _safe_step(self, sid: int):
        try:
            await self.step(sid)
        except Exception as exc:
            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)
                if s:
                    s.running = False
                    s.paused = False
                    s.last_error = str(exc)
                    s.phase = "ERROR"
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    await self._drop_client(s.user_id, s.account_id)
            finally:
                db.close()

    async def _currency_for(self, db, s) -> str:
        account = (
            db.query(DerivAccount)
            .filter(
                DerivAccount.user_id == s.user_id,
                DerivAccount.account_id == s.account_id,
            )
            .first()
        )
        return (
            str(account.currency).upper()
            if account and account.currency
            else "USD"
        )

    async def _request_proposal_payload(
        self,
        client,
        *,
        symbol,
        digit,
        stake,
        trade_no,
        currency,
    ):
        proposal = await client.proposal_digitmatch(
            symbol=symbol,
            digit=digit,
            amount=stake,
            duration=1,
            currency=currency,
        )

        p = proposal.get("proposal") or {}
        if not p.get("id"):
            raise RuntimeError(
                f"PROPOSAL: Deriv returned no proposal id; keys={list(proposal.keys())}"
            )

        return {
            "proposal_id": p["id"],
            "ask_price": float(p.get("ask_price") or stake),
            "payout": float(p.get("payout") or 0),
            "digit": int(digit),
            "stake": float(stake),
            "trade_no": int(trade_no),
            "currency": currency,
        }

    async def step(self, sid: int):
        async with self._lock(sid):
            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)

                if not s or not s.running or s.paused:
                    return

                if s.last_error:
                    s.last_error = None
                    db.commit()

                client = await self._client(s.user_id, s.account_id)

                if s.open_contract_id:
                    if sid not in self.contract_subscriptions:
                        await self._subscribe_open_contract(
                            sid=sid,
                            user_id=s.user_id,
                            account_id=s.account_id,
                            contract_id=str(s.open_contract_id),
                            client=client,
                        )

                    # Keep the UI truthful: current contract is open, but the next
                    # recovery proposal may already be ready in memory.
                    s.phase = (
                        "RECOVERY_PREARMED"
                        if sid in self.prefetched_recovery
                        else "PIPELINE_ACTIVE"
                    )
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

                if str(s.account_mode).upper() != "DEMO":
                    s.running = False
                    s.phase = "REAL_AUTOMATION_DISABLED"
                    s.last_error = (
                        "Automated server execution is DEMO-only in this build."
                    )
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                currency = await self._currency_for(db, s)

                # If this step follows a loss, use the prefetched proposal first.
                prefetched = self.prefetched_recovery.pop(sid, None)
                if prefetched:
                    s.phase = "BUYING_PREARMED"
                    s.updated_at = datetime.utcnow()
                    db.commit()

                    try:
                        await self._execute_demo_buy(
                            db, s, client, prefetched, prearmed=True
                        )
                        return
                    except Exception:
                        # Proposal can expire/stale. Fall back to a fresh quote.
                        pass

                s.phase = "REQUESTING_PROPOSAL"
                s.updated_at = datetime.utcnow()
                db.commit()

                try:
                    payload = await self._request_proposal_payload(
                        client,
                        symbol=s.symbol,
                        digit=s.candidate_digit,
                        stake=s.current_stake,
                        trade_no=s.current_trade + 1,
                        currency=currency,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"PROPOSAL [{s.symbol}/{currency}/digit {s.candidate_digit}]: {exc}"
                    ) from exc

                await self._execute_demo_buy(
                    db, s, client, payload, prearmed=False
                )

            finally:
                db.close()

    async def _execute_demo_buy(
        self,
        db,
        s,
        client,
        payload,
        *,
        prearmed: bool,
    ):
        if str(s.account_mode).upper() != "DEMO":
            raise RuntimeError("Automated purchase blocked outside DEMO mode")

        s.phase = "BUYING_PREARMED" if prearmed else "BUYING"
        s.updated_at = datetime.utcnow()
        db.commit()

        result = await client.buy(
            payload["proposal_id"],
            payload["ask_price"],
            demo=True,
        )

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
        s.phase = "PIPELINE_ACTIVE"
        s.current_trade += 1
        s.pending_trade_json = None
        s.pending_real_confirmation = False
        s.last_error = None
        s.updated_at = datetime.utcnow()
        db.commit()

        # Pre-arm the next recovery proposal immediately after BUY confirmation.
        # Do this BEFORE waiting for the open-contract subscription request so
        # that a Deriv subscription round-trip is never on the recovery critical
        # path. No paid next contract is purchased here.
        if s.current_trade < s.max_trades:
            asyncio.create_task(
                self._prefetch_next_recovery(
                    sid=s.id,
                    user_id=s.user_id,
                    account_id=s.account_id,
                    symbol=s.symbol,
                    digit=int(s.candidate_digit),
                    next_stake=round(
                        float(s.current_stake) * float(s.multiplier), 2
                    ),
                    next_trade_no=int(s.current_trade) + 1,
                )
            )

        await self._subscribe_open_contract(
            sid=s.id,
            user_id=s.user_id,
            account_id=s.account_id,
            contract_id=contract_id,
            client=client,
        )

    async def _prefetch_next_recovery(
        self,
        *,
        sid,
        user_id,
        account_id,
        symbol,
        digit,
        next_stake,
        next_trade_no,
    ):
        try:
            client = await self._client(user_id, account_id)

            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)
                if not s or not s.running or not s.open_contract_id:
                    return
                currency = await self._currency_for(db, s)
            finally:
                db.close()

            payload = await self._request_proposal_payload(
                client,
                symbol=symbol,
                digit=digit,
                stake=next_stake,
                trade_no=next_trade_no,
                currency=currency,
            )

            # Only keep it if the same session is still on the same open trade.
            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)
                if (
                    s
                    and s.running
                    and s.open_contract_id
                    and int(s.current_trade) + 1 == int(next_trade_no)
                ):
                    self.prefetched_recovery[sid] = payload
                    s.phase = "RECOVERY_PREARMED"
                    s.updated_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()

        except Exception:
            # Prefetch is only an optimization. Fresh proposal remains fallback.
            self.prefetched_recovery.pop(sid, None)

    async def _subscribe_open_contract(
        self,
        *,
        sid,
        user_id,
        account_id,
        contract_id,
        client,
    ):
        old_sub = self.contract_subscriptions.pop(sid, None)
        if old_sub:
            try:
                await client.forget(old_sub)
            except Exception:
                pass

        old_poll = self.contract_poll_tasks.pop(sid, None)
        if old_poll and not old_poll.done():
            old_poll.cancel()

        async def on_contract_update(data: dict):
            await self._handle_contract_update(
                sid=sid,
                user_id=user_id,
                account_id=account_id,
                contract_id=contract_id,
                data=data,
            )

        sub_id = await client.subscribe_contract(
            contract_id,
            on_contract_update,
        )

        if sub_id:
            self.contract_subscriptions[sid] = sub_id
            return

        # Deriv occasionally returns a valid proposal_open_contract response
        # for a 1-tick contract without a subscription id. The websocket
        # client has already delivered that first response to the callback.
        # If it was not yet sold, poll the contract briefly instead of
        # failing the entire trading session.
        async def poll_until_sold():
            try:
                for _ in range(600):  # up to ~30 seconds
                    await asyncio.sleep(0.05)

                    data = await client.contract_status(contract_id)
                    await on_contract_update(data)

                    poc = data.get("proposal_open_contract") or {}
                    if poc.get("is_sold"):
                        return

                    # Stop polling if this contract is no longer the active
                    # one for the session.
                    db = SessionLocal()
                    try:
                        session = db.get(TradingSession, sid)
                        if (
                            not session
                            or str(session.open_contract_id or "")
                            != str(contract_id)
                        ):
                            return
                    finally:
                        db.close()

                raise RuntimeError(
                    f"Contract {contract_id} did not settle within polling window"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Surface a real settlement-monitor failure through the normal
                # session error path rather than silently losing the contract.
                db = SessionLocal()
                try:
                    session = db.get(TradingSession, sid)
                    if (
                        session
                        and str(session.open_contract_id or "")
                        == str(contract_id)
                    ):
                        session.running = False
                        session.paused = False
                        session.phase = "ERROR"
                        session.last_error = (
                            f"Contract settlement monitor failed: {exc}"
                        )
                        session.updated_at = datetime.utcnow()
                        db.commit()
                finally:
                    db.close()
            finally:
                self.contract_poll_tasks.pop(sid, None)

        self.contract_poll_tasks[sid] = asyncio.create_task(
            poll_until_sold()
        )

    async def _forget_quietly(self, client, sub_id):
        try:
            await client.forget(sub_id)
        except Exception:
            pass

    async def _handle_contract_update(
        self,
        *,
        sid,
        user_id,
        account_id,
        contract_id,
        data,
    ):
        poc = data.get("proposal_open_contract") or {}
        if not poc.get("is_sold"):
            return

        async with self._lock(sid):
            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)
                if not s:
                    return

                if str(s.open_contract_id or "") != str(contract_id):
                    return

                profit = float(poc.get("profit") or 0)
                s.pnl = float(s.pnl or 0) + profit

                log = (
                    db.query(TradeLog)
                    .filter(
                        TradeLog.trading_session_id == s.id,
                        TradeLog.contract_id == contract_id,
                    )
                    .order_by(TradeLog.id.desc())
                    .first()
                )

                if log:
                    log.status = "SETTLED"
                    log.profit = profit
                    log.settled_at = datetime.utcnow()
                    log.raw_json = json.dumps(data)

                account = (
                    db.query(DerivAccount)
                    .filter(
                        DerivAccount.user_id == user_id,
                        DerivAccount.account_id == account_id,
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
                    self.prefetched_recovery.pop(sid, None)
                    s.current_stake = s.base_stake
                    s.phase = "WON"
                    s.running = False
                else:
                    if s.current_trade >= s.max_trades:
                        self.prefetched_recovery.pop(sid, None)
                        s.phase = "MAX_TRADES_REACHED"
                        s.running = False
                    else:
                        s.current_stake = round(
                            float(s.current_stake) * float(s.multiplier),
                            2,
                        )
                        s.phase = (
                            "RECOVERY_PREARMED"
                            if sid in self.prefetched_recovery
                            else "RECOVERING"
                        )

                s.updated_at = datetime.utcnow()
                db.commit()

            finally:
                db.close()

        client = self.clients.get((user_id, account_id))
        sub_id = self.contract_subscriptions.pop(sid, None)
        if client and sub_id:
            # Forgetting the old subscription is housekeeping, not part of the
            # trade critical path. Waiting for its WebSocket round trip here can
            # make a 1-tick recovery miss the next market tick.
            asyncio.create_task(self._forget_quietly(client, sub_id))

        # Confirmed DEMO loss: run the next step immediately.
        db = SessionLocal()
        try:
            s = db.get(TradingSession, sid)
            should_continue = bool(
                s
                and s.running
                and not s.paused
                and not s.open_contract_id
                and int(s.current_trade) < int(s.max_trades)
            )
        finally:
            db.close()

        if should_continue:
            # The settlement callback already runs as its own task and the
            # session lock has been released above. Continue the recovery now
            # instead of adding another scheduler hop.
            await self._safe_step(sid)

    async def confirm_real(self, user_id: str, session_id: int):
        raise RuntimeError(
            "Automated REAL-money execution is disabled in this low-latency build."
        )


engine = MultiUserEngine()
