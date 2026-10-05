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
    DEMO-only event-driven execution engine.

    Key change from the previous worker:
    - no 0.5-second settlement polling loop
    - no foreground WAITING_SETTLEMENT gate
    - each DEMO contract gets a proposal_open_contract subscription
    - settlement is processed as an async callback
    - recovery is scheduled immediately after a confirmed DEMO loss
    - REAL automated purchases remain disabled
    """

    def __init__(self):
        self.task = None
        self.clients = {}  # key=(user_id, account_id)
        self.contract_subscriptions = {}  # session_id -> subscription_id
        self.session_tasks = {}  # session_id -> asyncio.Task
        self.session_locks = {}  # session_id -> asyncio.Lock

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
        # This loop only discovers sessions that need a fresh execution task.
        # Contract settlement itself is push-driven by Deriv subscriptions.
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

            # Lower orchestration latency without settlement polling.
            await asyncio.sleep(0.05)

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

                # If a DEMO contract is already open, do not poll it.
                # Ensure it has a push subscription and leave the foreground lane free.
                if s.open_contract_id:
                    if sid not in self.contract_subscriptions:
                        await self._subscribe_open_contract(
                            sid=sid,
                            user_id=s.user_id,
                            account_id=s.account_id,
                            contract_id=str(s.open_contract_id),
                            client=client,
                        )

                    s.phase = "PIPELINE_ACTIVE"
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

                # Automated execution is deliberately DEMO-only.
                if str(s.account_mode).upper() != "DEMO":
                    s.running = False
                    s.phase = "REAL_AUTOMATION_DISABLED"
                    s.last_error = (
                        "Automated server execution is DEMO-only in this build. "
                        "REAL purchases require a separate explicit manual-confirmation flow."
                    )
                    s.updated_at = datetime.utcnow()
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
                s.updated_at = datetime.utcnow()
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

                payload = {
                    "proposal_id": p["id"],
                    "ask_price": float(p.get("ask_price") or s.current_stake),
                    "payout": float(p.get("payout") or 0),
                    "digit": int(s.candidate_digit),
                    "stake": float(s.current_stake),
                    "trade_no": int(s.current_trade) + 1,
                    "currency": currency,
                }

                await self._execute_demo_buy(db, s, client, payload)

            finally:
                db.close()

    async def _execute_demo_buy(self, db, s, client, payload):
        if str(s.account_mode).upper() != "DEMO":
            raise RuntimeError("Automated purchase blocked outside DEMO mode")

        s.phase = "BUYING"
        s.updated_at = datetime.utcnow()
        db.commit()

        try:
            result = await client.buy(
                payload["proposal_id"],
                payload["ask_price"],
                demo=True,
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
        s.phase = "PIPELINE_ACTIVE"
        s.current_trade += 1
        s.pending_trade_json = None
        s.pending_real_confirmation = False
        s.last_error = None
        s.updated_at = datetime.utcnow()
        db.commit()

        await self._subscribe_open_contract(
            sid=s.id,
            user_id=s.user_id,
            account_id=s.account_id,
            contract_id=contract_id,
            client=client,
        )

    async def _subscribe_open_contract(
        self,
        *,
        sid: int,
        user_id: str,
        account_id: str,
        contract_id: str,
        client: DerivWS,
    ):
        # Replace any stale subscription associated with this session.
        old_sub = self.contract_subscriptions.pop(sid, None)
        if old_sub:
            try:
                await client.forget(old_sub)
            except Exception:
                pass

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
        self.contract_subscriptions[sid] = sub_id

    async def _handle_contract_update(
        self,
        *,
        sid: int,
        user_id: str,
        account_id: str,
        contract_id: str,
        data: dict,
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

                # Ignore a late update from an older/replaced contract.
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
                    s.current_stake = s.base_stake
                    s.phase = "WON"
                    s.running = False
                else:
                    if s.current_trade >= s.max_trades:
                        s.phase = "MAX_TRADES_REACHED"
                        s.running = False
                    else:
                        s.current_stake = round(
                            float(s.current_stake) * float(s.multiplier),
                            2,
                        )
                        s.phase = "RECOVERING"

                s.updated_at = datetime.utcnow()
                db.commit()

            finally:
                db.close()

        # Unsubscribe after the sold update.
        client = self.clients.get((user_id, account_id))
        sub_id = self.contract_subscriptions.pop(sid, None)
        if client and sub_id:
            try:
                await client.forget(sub_id)
            except Exception:
                pass

        # A confirmed DEMO loss schedules the next recovery immediately.
        db = SessionLocal()
        try:
            s = db.get(TradingSession, sid)
            should_continue = bool(
                s
                and s.running
                and not s.paused
                and not s.open_contract_id
                and str(s.phase).upper() == "RECOVERING"
                and int(s.current_trade) < int(s.max_trades)
            )
        finally:
            db.close()

        if should_continue:
            task = self.session_tasks.get(sid)
            if not task or task.done():
                self.session_tasks[sid] = asyncio.create_task(
                    self._safe_step(sid)
                )

    async def confirm_real(self, user_id: str, session_id: int):
        raise RuntimeError(
            "Automated REAL-money execution is disabled in this event-driven build."
        )


engine = MultiUserEngine()
