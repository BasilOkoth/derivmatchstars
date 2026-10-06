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
        # Settlement subscriptions are keyed by (session_id, contract_id)
        # because strategy execution can advance before Deriv's official
        # settlement event for the previous 1-tick contract arrives.
        self.contract_subscriptions = {}
        self.contract_poll_tasks = {}

        # One live tick subscription per running session/symbol. Ticks drive
        # the strategy immediately; official contract settlement is accounting.
        self.tick_subscriptions = {}
        self.latest_tick_epoch = {}
        self.latest_ticks = {}
        self.fast_contracts = {}  # sid -> currently strategy-active contract

        self.session_tasks = {}
        self.session_locks = {}
        self.prefetched_recovery = {}  # sid -> payload
        self.prefetch_tasks = {}  # sid -> exactly one in-flight proposal prefetch

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

    @staticmethod
    def _tick_last_digit(tick: dict):
        quote = tick.get("quote")
        if quote is None:
            return None

        pip_size = tick.get("pip_size")
        try:
            if pip_size is not None:
                text = f"{float(quote):.{int(pip_size)}f}"
            else:
                text = str(quote)
        except Exception:
            text = str(quote)

        digits = [ch for ch in text if ch.isdigit()]
        return int(digits[-1]) if digits else None

    async def _ensure_tick_subscription(
        self,
        *,
        sid,
        user_id,
        account_id,
        symbol,
        client,
    ):
        existing = self.tick_subscriptions.get(sid)
        if existing and existing.get("symbol") == str(symbol):
            return

        if existing:
            old_id = existing.get("subscription_id")
            if old_id:
                asyncio.create_task(self._forget_quietly(client, old_id))
            self.tick_subscriptions.pop(sid, None)

        async def on_tick(data: dict):
            await self._handle_strategy_tick(
                sid=sid,
                user_id=user_id,
                account_id=account_id,
                symbol=str(symbol),
                data=data,
            )

        sub_id = await client.subscribe_ticks(str(symbol), on_tick)
        self.tick_subscriptions[sid] = {
            "subscription_id": sub_id,
            "symbol": str(symbol),
        }

    async def _handle_strategy_tick(
        self,
        *,
        sid,
        user_id,
        account_id,
        symbol,
        data,
    ):
        tick = data.get("tick") or {}
        epoch = int(tick.get("epoch") or 0)
        if tick:
            self.latest_ticks[sid] = dict(tick)
        if epoch:
            self.latest_tick_epoch[sid] = max(
                int(self.latest_tick_epoch.get(sid) or 0),
                epoch,
            )

        active = self.fast_contracts.get(sid)
        if not active:
            return
        if str(active.get("symbol")) != str(symbol):
            return
        if active.get("decided"):
            return

        # A 1-tick DIGITMATCH settles on the first market tick after the buy
        # was armed. Ignore any tick already seen before BUY confirmation.
        armed_after_epoch = int(active.get("armed_after_epoch") or 0)
        if epoch and armed_after_epoch and epoch <= armed_after_epoch:
            return

        digit = self._tick_last_digit(tick)
        if digit is None:
            return

        # Mark before any await so duplicate callbacks cannot trigger two buys.
        active["decided"] = True
        active["decision_epoch"] = epoch
        active["observed_digit"] = digit

        target_digit = int(active["target_digit"])
        contract_id = str(active["contract_id"])
        is_win = digit == target_digit
        active["fast_result"] = "WIN" if is_win else "LOSS"

        async with self._lock(sid):
            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)
                if not s:
                    return

                # Ignore a stale tick callback from an older strategy contract.
                current_fast = self.fast_contracts.get(sid)
                if (
                    not current_fast
                    or str(current_fast.get("contract_id")) != contract_id
                ):
                    return

                if is_win:
                    # Strategy outcome is known from the live settlement tick.
                    # Stop immediately. Deriv's official is_sold event remains
                    # subscribed and will update authoritative P/L in background.
                    self.prefetched_recovery.pop(sid, None)
                    s.running = False
                    s.paused = False
                    s.phase = "FAST_WON"
                    s.last_error = None
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                # Mismatch = strategy loss. Advance immediately from this tick;
                # do NOT wait for proposal_open_contract.is_sold.
                if int(s.current_trade) >= int(s.max_trades):
                    self.prefetched_recovery.pop(sid, None)
                    s.running = False
                    s.phase = "MAX_TRADES_REACHED"
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                s.current_stake = round(
                    float(s.current_stake) * float(s.multiplier),
                    2,
                )
                s.phase = "FAST_RECOVERING"
                s.updated_at = datetime.utcnow()
                db.commit()

                payload = self.prefetched_recovery.pop(sid, None)
                currency = await self._currency_for(db, s)

                expected_trade_no = int(s.current_trade) + 1

                # If the prefetch request is already in flight, do NOT create a
                # duplicate proposal request for the same recovery. Give that
                # existing request a short chance to finish first.
                if not payload:
                    prefetch_task = self.prefetch_tasks.get(sid)
                    if prefetch_task and not prefetch_task.done():
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(prefetch_task),
                                timeout=0.8,
                            )
                        except asyncio.TimeoutError:
                            pass
                        except Exception:
                            pass
                        payload = self.prefetched_recovery.pop(sid, None)

                if (
                    not payload
                    or int(payload.get("trade_no") or 0) != expected_trade_no
                    or int(payload.get("digit")) != int(s.candidate_digit)
                    or abs(
                        float(payload.get("stake") or 0)
                        - float(s.current_stake)
                    ) > 0.005
                ):
                    payload = await self._request_proposal_payload(
                        await self._client(user_id, account_id),
                        symbol=s.symbol,
                        digit=s.candidate_digit,
                        stake=s.current_stake,
                        trade_no=expected_trade_no,
                        currency=currency,
                    )

                client = await self._client(user_id, account_id)
                await self._execute_demo_buy(
                    db,
                    s,
                    client,
                    payload,
                    prearmed=True,
                )
            finally:
                db.close()

    async def _forget_quietly(self, client, sub_id):
        try:
            await client.forget(sub_id)
        except Exception:
            pass

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

                await self._ensure_tick_subscription(
                    sid=s.id,
                    user_id=s.user_id,
                    account_id=s.account_id,
                    symbol=s.symbol,
                    client=client,
                )

                if s.open_contract_id:
                    contract_key = (sid, str(s.open_contract_id))
                    if contract_key not in self.contract_subscriptions:
                        asyncio.create_task(self._subscribe_open_contract(
                            sid=sid,
                            user_id=s.user_id,
                            account_id=s.account_id,
                            contract_id=str(s.open_contract_id),
                            client=client,
                        ))

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

        await self._ensure_tick_subscription(
            sid=s.id,
            user_id=s.user_id,
            account_id=s.account_id,
            symbol=s.symbol,
            client=client,
        )

        s.phase = "BUYING_PREARMED" if prearmed else "BUYING"
        s.updated_at = datetime.utcnow()
        db.commit()

        # Snapshot the newest tick already observed BEFORE sending BUY.
        # The strategy will evaluate the first later tick for this 1-tick trade.
        armed_after_epoch = int(self.latest_tick_epoch.get(s.id) or 0)

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

        # This is the ONLY contract whose next tick should drive strategy.
        # Older contracts may still be awaiting official settlement in the
        # background and must not block this one.
        purchase_epoch = int(
            buy.get("start_time")
            or buy.get("purchase_time")
            or armed_after_epoch
            or 0
        )
        decision_after_epoch = max(armed_after_epoch, purchase_epoch)

        self.fast_contracts[s.id] = {
            "contract_id": contract_id,
            "target_digit": int(payload["digit"]),
            "symbol": str(s.symbol),
            "trade_no": int(payload["trade_no"]),
            "armed_after_epoch": decision_after_epoch,
            "decided": False,
        }

        s.open_contract_id = contract_id
        s.phase = "PIPELINE_ACTIVE"
        s.current_trade += 1
        s.pending_trade_json = None
        s.pending_real_confirmation = False
        s.last_error = None
        s.updated_at = datetime.utcnow()
        db.commit()

        # A market tick can arrive while awaiting the BUY response. The socket
        # reader stores the newest tick even before contract_id is known.
        # Re-evaluate that cached tick if it is newer than the purchase epoch,
        # otherwise the strategy could become exactly one tick late.
        cached_tick = self.latest_ticks.get(s.id)
        if cached_tick:
            cached_epoch = int(cached_tick.get("epoch") or 0)
            if cached_epoch > decision_after_epoch:
                asyncio.create_task(
                    self._handle_strategy_tick(
                        sid=s.id,
                        user_id=s.user_id,
                        account_id=s.account_id,
                        symbol=str(s.symbol),
                        data={"tick": dict(cached_tick)},
                    )
                )

        # Pre-arm the NEXT recovery immediately. This is deliberately started
        # before the official settlement subscription round-trip.
        if s.current_trade < s.max_trades:
            existing_prefetch = self.prefetch_tasks.get(s.id)
            if not existing_prefetch or existing_prefetch.done():
                task = asyncio.create_task(
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
                self.prefetch_tasks[s.id] = task

        # Official settlement is bookkeeping/reconciliation only and runs
        # independently of the live-tick strategy path.
        asyncio.create_task(
            self._subscribe_open_contract(
                sid=s.id,
                user_id=s.user_id,
                account_id=s.account_id,
                contract_id=contract_id,
                client=client,
            )
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
        finally:
            current = self.prefetch_tasks.get(sid)
            if current is asyncio.current_task():
                self.prefetch_tasks.pop(sid, None)

    async def _subscribe_open_contract(
        self,
        *,
        sid,
        user_id,
        account_id,
        contract_id,
        client,
    ):
        key = (sid, str(contract_id))
        if key in self.contract_subscriptions:
            return

        async def on_contract_update(data: dict):
            await self._handle_contract_update(
                sid=sid,
                user_id=user_id,
                account_id=account_id,
                contract_id=str(contract_id),
                data=data,
            )

        try:
            sub_id = await client.subscribe_contract(
                str(contract_id),
                on_contract_update,
            )
        except Exception:
            sub_id = None

        if sub_id:
            self.contract_subscriptions[key] = sub_id
            return

        # If Deriv omits a subscription id for a short 1-tick contract,
        # reconcile it by polling in the background. This never gates strategy.
        if key in self.contract_poll_tasks:
            return

        async def poll_until_sold():
            try:
                for _ in range(600):
                    await asyncio.sleep(0.05)
                    data = await client.contract_status(str(contract_id))
                    poc = data.get("proposal_open_contract") or {}
                    await on_contract_update(data)
                    if poc.get("is_sold"):
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                # Background reconciliation failure must not create a second
                # trade or freeze the live-tick strategy. The OPEN TradeLog
                # remains visible for later reconciliation.
                return
            finally:
                self.contract_poll_tasks.pop(key, None)

        self.contract_poll_tasks[key] = asyncio.create_task(
            poll_until_sold()
        )

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

        key = (sid, str(contract_id))

        async with self._lock(sid):
            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)
                if not s:
                    return

                log = (
                    db.query(TradeLog)
                    .filter(
                        TradeLog.trading_session_id == sid,
                        TradeLog.contract_id == str(contract_id),
                    )
                    .order_by(TradeLog.id.desc())
                    .first()
                )

                # proposal_open_contract subscriptions can send the sold state
                # more than once. Account exactly once.
                if log and str(log.status).upper() == "SETTLED":
                    return

                profit = float(poc.get("profit") or 0)

                if log:
                    log.status = "SETTLED"
                    log.profit = profit
                    log.settled_at = datetime.utcnow()
                    log.raw_json = json.dumps(data)

                s.pnl = float(s.pnl or 0) + profit

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

                # Never clear a newer strategy contract while settling an older
                # one in the background.
                if str(s.open_contract_id or "") == str(contract_id):
                    s.open_contract_id = None

                # Compare the fast tick decision with Deriv's authoritative
                # financial outcome. Do not use this event to advance strategy.
                fast = self.fast_contracts.get(sid)
                if fast and str(fast.get("contract_id")) == str(contract_id):
                    official = "WIN" if profit > 0 else "LOSS"
                    fast["official_result"] = official

                    if fast.get("fast_result") and fast["fast_result"] != official:
                        # A mismatch means tick/contract correlation is wrong.
                        # Stop rather than risk cascading from a wrong tick.
                        s.running = False
                        s.phase = "RECONCILE_MISMATCH"
                        s.last_error = (
                            f"Fast tick result {fast['fast_result']} disagreed "
                            f"with Deriv settlement {official} for contract "
                            f"{contract_id}"
                        )

                s.updated_at = datetime.utcnow()
                db.commit()
            finally:
                db.close()

        sub_id = self.contract_subscriptions.pop(key, None)
        client = self.clients.get((user_id, account_id))
        if client and sub_id:
            asyncio.create_task(self._forget_quietly(client, sub_id))

        poll = self.contract_poll_tasks.pop(key, None)
        if poll and poll is not asyncio.current_task() and not poll.done():
            poll.cancel()

    async def confirm_real(self, user_id: str, session_id: int):
        raise RuntimeError(
            "Automated REAL-money execution is disabled in this low-latency build."
        )


engine = MultiUserEngine()
