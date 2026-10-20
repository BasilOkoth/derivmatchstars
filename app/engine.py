import asyncio
import json
import uuid
import time
import logging
from datetime import datetime
from collections import deque

from .db import SessionLocal
from .models import TradingSession, DerivCredential, DerivAccount, TradeLog
from .config import settings
from .security import decrypt_token
from .deriv_rest import get_ws_url
from .deriv_ws import DerivWS
from .digit_score import DigitScoreEngine


logger = logging.getLogger(__name__)


class MultiUserEngine:
    """
    DigitMatchStar low-latency engine for the selected Deriv account.

    Strategy invariant:
      1. Rank and submit BUY for Trade N.
      2. Arm Trade N only after Deriv acknowledges the BUY.
      3. The first genuinely new server tick after that BUY acknowledgment
         drives the immediate strategy decision:
            target digit == tick last digit -> WIN -> stop immediately
            target digit != tick last digit -> LOSS -> advance immediately
      3. After each tick, the freshest V1 rank #1 is selected.
      4. On a fast loss, BUY Trade N+1 directly from contract parameters.
      5. Deriv proposal_open_contract settlement runs in the background only
         for authoritative P/L/accounting/reconciliation.
      6. If the fast tick result disagrees with Deriv's eventual settlement,
         stop with RECONCILE_MISMATCH rather than silently continuing.

    DEMO and REAL sessions use the same strategy, purchase claims, tick
    decisions, recovery progression and settlement reconciliation. The session
    account_id determines which Deriv account receives each purchase.
    """

    def __init__(self):
        self.task = None
        self.clients = {}  # (user_id, account_id) -> DerivWS

        self.session_tasks = {}
        self.session_locks = {}

        # Live tick stream state.
        self.tick_subscriptions = {}  # sid -> {subscription_id, symbol}
        self.latest_tick_epoch = {}
        self.latest_ticks = {}
        self.latest_tick_received_at = {}
        # Exact callback sequence for next-tick execution. Deriv tick epochs are
        # whole seconds, so multiple consecutive ticks can share one epoch.
        self.tick_sequence = {}  # sid -> monotonically increasing tick number
        # Last known decimal precision for each session's selected symbol.
        # Used when a live tick omits pip_size so trailing-zero digits remain
        # identical to Deriv/browser formatting.
        self.tick_precision = {}  # sid -> decimal places
        self.contract_probe_at = {}
        self.contract_probe_tasks = {}
        # DEMO-only stale-contract recovery. A 1-tick contract must not keep a
        # restarted worker permanently trapped in WAITING_OFFICIAL_SETTLEMENT.
        self.contract_probe_unsold = {}   # (sid, contract_id) -> successful unsold probes
        self.contract_probe_errors = {}   # (sid, contract_id) -> reconciliation errors

        # Only the newest strategy-active paid contract belongs here.
        # Older contracts can still settle in the background.
        self.fast_contracts = {}  # sid -> newest strategy-active contract

        # Exact contract execution evidence exposed to the dashboard. Unlike
        # TradingSession.candidate_digit, target_digit here is immutable for
        # the purchased contract and is never replaced by the NEXT V1 target.
        self.execution_contract_state = {}  # sid -> current/most recent contract evidence

        # A decided contract can be retired from the active execution slot
        # while its official Deriv settlement is still pending. This preserves
        # fast-vs-official reconciliation without blocking the next trade.
        self.retired_fast_contracts = {}  # (sid, contract_id) -> metadata

        # Settlement bookkeeping keyed per individual contract.
        self.contract_subscriptions = {}  # (sid, contract_id) -> sub_id
        self.contract_poll_tasks = {}  # fallback only

        # Latest live V1 rank #1 for the NEXT trade.
        # This may change while a purchased contract is open; the purchased
        # contract itself remains immutable at Deriv.
        self.live_next_target = {}  # sid -> digit

        # Unified 0-9 scoring + target recycling.
        self.digit_scorer = DigitScoreEngine(recycle_after=3, min_history=10, max_history=100)

        # V1 MARGIN GATE
        # Rank #1 is executable only when its lead over rank #2 reaches the
        # user-configured minimum. Shared by DEMO and REAL target selection.
        self.minimum_v1_margin_default = 3.0
        self.minimum_v1_margin_by_sid = {}
        self.digit_history = {}          # sid -> deque(maxlen=100)
        self.digit_score_snapshots = {}  # sid -> latest ranking
        # Process memory is lost on Render restart. Rebuild DigitScore from
        # Deriv's recent ticks_history before the next cycle starts.
        self.history_bootstrap_tasks = {}   # sid -> asyncio.Task
        self.history_bootstrap_generation = {}  # sid -> client connection generation
        self.locked_target_snapshots = {}  # sid -> execution snapshot frozen at block selection
        self.last_settlement_by_sid = {}  # sid -> latest authoritative Deriv settlement
        # Identifies this server process in persisted execution evidence.
        # Useful for detecting overlapping Render instances during deploy/restart.
        self.instance_id = uuid.uuid4().hex[:12]

        # BUY RateLimit protection. The worker loop runs very frequently, so a
        # rejected BUY must create a real cooldown barrier; otherwise the next
        # worker pass can immediately hammer the same logical trade again.
        self.buy_rate_limit_until = {}   # sid -> monotonic deadline
        self.buy_rate_limit_streak = {}  # sid -> consecutive explicit rejects

    async def start(self):
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_forever())

    def get_minimum_v1_margin(self, sid: int) -> float:
        try:
            value = float(
                self.minimum_v1_margin_by_sid.get(
                    int(sid),
                    self.minimum_v1_margin_default,
                )
            )
        except (TypeError, ValueError):
            value = float(self.minimum_v1_margin_default)
        return max(0.0, min(50.0, value))

    def set_minimum_v1_margin(self, sid: int, value: float) -> float:
        value = max(0.0, min(50.0, float(value)))
        self.minimum_v1_margin_by_sid[int(sid)] = value

        snapshot = self.digit_score_snapshots.get(int(sid))
        if isinstance(snapshot, dict):
            margin = snapshot.get("top_margin")
            try:
                margin_value = float(margin) if margin is not None else None
            except (TypeError, ValueError):
                margin_value = None

            eligible = bool(
                snapshot.get("ready")
                and margin_value is not None
                and margin_value >= value
            )
            snapshot["minimum_v1_margin"] = value
            snapshot["margin_eligible"] = eligible
            snapshot["margin_status"] = (
                "READY" if eligible
                else "WAITING_MARGIN" if snapshot.get("ready")
                else "WARMING"
            )

        return value

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
        """
        This loop starts sessions and handles recovery from process restarts.

        It is NOT the settlement timing loop. Live tick callbacks drive strategy.
        """
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
            message = str(exc)
            lower = message.lower()

            db = SessionLocal()
            try:
                s = db.get(TradingSession, sid)
                if not s:
                    return

                # A BUY request is never retried when its outcome is uncertain.
                # Preserve the hard-stop phase instead of converting it into a
                # recoverable proposal/rate-limit loop.
                if (
                    "buy_uncertain" in lower
                    or "buy_claim_lost" in lower
                    or "buy_sequence_mismatch" in lower
                ):
                    s.running = False
                    s.paused = False
                    if "buy_claim_lost" in lower:
                        s.phase = "BUY_CLAIM_LOST"
                    elif "buy_sequence_mismatch" in lower:
                        s.phase = "BUY_SEQUENCE_MISMATCH"
                    else:
                        s.phase = "BUY_UNCERTAIN_STOPPED"
                    s.last_error = message
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                # Proposal throttling is recoverable. Do not convert it into a
                # fatal SERVER ERROR and destroy the session.
                if "ratelimit" in lower or "rate limit" in lower:
                    s.running = True
                    s.paused = False
                    s.last_error = message
                    s.phase = "RATE_LIMIT_BACKOFF"
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    await asyncio.sleep(2.0)
                    return

                s.running = False
                s.paused = False
                s.last_error = message
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

    @staticmethod
    def _direct_buy_payload(
        *,
        symbol,
        digit,
        stake,
        trade_no,
        currency,
    ):
        return {
            "execution_mode": "DIRECT_PARAMETERS",
            "symbol": str(symbol),
            "digit": int(digit),
            "stake": round(float(stake), 2),
            "trade_no": int(trade_no),
            "currency": str(currency or "USD").upper(),
            # Kept for TradeLog compatibility; authoritative values are
            # overwritten from Deriv's buy response when available.
            "ask_price": round(float(stake), 2),
            "payout": None,
        }

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
                "PROPOSAL: Deriv returned no proposal id; "
                f"keys={list(proposal.keys())}"
            )

        return {
            "proposal_id": p["id"],
            "ask_price": float(p.get("ask_price") or stake),
            "payout": float(p.get("payout") or 0),
            "digit": int(digit),
            "stake": float(stake),
            "trade_no": int(trade_no),
            "currency": currency,
            # Proposal IDs belong to the authenticated WebSocket session that
            # created them. If the socket reconnects before BUY, refresh rather
            # than sending an ID that Deriv no longer knows.
            "connection_generation": int(
                getattr(client, "connection_generation", 0) or 0
            ),
        }

    @staticmethod
    def _pip_decimals(pip_size):
        """Normalize Deriv pip_size into decimal places.

        Live ticks commonly expose pip_size as an integer decimal count
        (for example 3), while metadata can expose a step (for example 0.001).
        Support both forms so browser/server digit extraction stays identical.
        """
        if pip_size is None:
            return None
        try:
            p = float(pip_size)
        except (TypeError, ValueError):
            return None

        if p.is_integer() and 0 <= p <= 10:
            return int(p)

        if 0 < p < 1:
            text = f"{p:.12f}".rstrip("0")
            if "." in text:
                return len(text.split(".", 1)[1])

        return None

    @classmethod
    def _canonical_tick_text(cls, tick: dict, fallback_decimals=None):
        quote = tick.get("quote")
        if quote is None:
            return None

        decimals = cls._pip_decimals(tick.get("pip_size"))
        if decimals is None and fallback_decimals is not None:
            try:
                decimals = int(fallback_decimals)
            except (TypeError, ValueError):
                decimals = None

        try:
            if decimals is not None and 0 <= int(decimals) <= 10:
                return f"{float(quote):.{int(decimals)}f}"
            return str(quote)
        except Exception:
            return str(quote)

    @classmethod
    def _tick_last_digit(cls, tick: dict, fallback_decimals=None):
        text = cls._canonical_tick_text(
            tick,
            fallback_decimals=fallback_decimals,
        )
        if not text:
            return None

        digits = [ch for ch in text if ch.isdigit()]
        return int(digits[-1]) if digits else None

    def _set_live_next_target(self, sid: int, digit):
        if digit is None:
            return False

        digit = int(digit)
        previous = self.live_next_target.get(sid)
        self.live_next_target[sid] = digit
        return previous != digit

    def _digit_history(self, sid: int):
        history = self.digit_history.get(sid)
        if history is None:
            history = deque(maxlen=100)
            self.digit_history[sid] = history
        return history

    def _score_all_digits(self, sid: int, exclude_digit=None):
        snapshot = self.digit_scorer.rank(
            list(self._digit_history(sid)),
            exclude_digit=exclude_digit,
        )

        # Stamp every ranking with the exact canonical SERVER tick that
        # produced it. This makes browser/server stream skew visible instead
        # of making two different ticks look like a mapping error.
        latest = dict(self.latest_ticks.get(int(sid)) or {})
        if latest:
            fallback_decimals = self.tick_precision.get(int(sid))
            canonical_text = self._canonical_tick_text(
                latest,
                fallback_decimals=fallback_decimals,
            )
            canonical_digit = self._tick_last_digit(
                latest,
                fallback_decimals=fallback_decimals,
            )
            rank_seq = int(
                latest.get("_dms_seq")
                or self.tick_sequence.get(int(sid), 0)
                or 0
            )
            rank_epoch = int(
                latest.get("epoch")
                or self.latest_tick_epoch.get(int(sid), 0)
                or 0
            )
            tick_decimals = self._pip_decimals(latest.get("pip_size"))
            if tick_decimals is None:
                tick_decimals = fallback_decimals

            snapshot["rank_seq"] = rank_seq or None
            snapshot["rank_epoch"] = rank_epoch or None
            snapshot["canonical_tick"] = {
                "seq": rank_seq or None,
                "epoch": rank_epoch or None,
                "quote": latest.get("quote"),
                "formatted_quote": canonical_text,
                "digit": (
                    int(canonical_digit)
                    if canonical_digit is not None
                    else None
                ),
                "pip_size": latest.get("pip_size"),
                "decimals": tick_decimals,
                "symbol": latest.get("symbol"),
            }
            snapshot["feed_state"] = "LIVE_RANK"
        else:
            snapshot["rank_seq"] = None
            snapshot["rank_epoch"] = None
            snapshot["canonical_tick"] = None
            snapshot["feed_state"] = "RANK_WITHOUT_LIVE_TICK"

        execution_state = self.execution_contract_state.get(int(sid))
        snapshot["execution_contract"] = (
            json.loads(json.dumps(execution_state))
            if isinstance(execution_state, dict)
            else None
        )

        margin = snapshot.get("top_margin")
        try:
            margin_value = float(margin) if margin is not None else None
        except (TypeError, ValueError):
            margin_value = None

        minimum_margin = self.get_minimum_v1_margin(sid)
        margin_eligible = bool(
            snapshot.get("ready")
            and margin_value is not None
            and margin_value >= minimum_margin
        )

        snapshot["minimum_v1_margin"] = minimum_margin
        snapshot["margin_eligible"] = margin_eligible
        snapshot["margin_status"] = (
            "READY" if margin_eligible
            else "WAITING_MARGIN" if snapshot.get("ready")
            else "WARMING"
        )

        self.digit_score_snapshots[sid] = snapshot
        return snapshot

    def _choose_scored_digit(self, sid: int, exclude_digit=None, *, lock_target=False):
        snapshot = self._score_all_digits(sid, exclude_digit=exclude_digit)
        digit = snapshot.get("selected_digit")

        # Execution gate: rank #1 is visible continuously, but it is not
        # executable until the separation from rank #2 reaches the minimum.
        if not snapshot.get("margin_eligible"):
            return None, snapshot

        if lock_target and digit is not None:
            self.locked_target_snapshots[sid] = {
                "digit": int(digit),
                "snapshot": json.loads(json.dumps(snapshot)),
                "locked_at": datetime.utcnow().isoformat(),
            }

        return (int(digit) if digit is not None else None), snapshot

    def _trade_score_evidence(self, sid: int, digit: int):
        """Return the exact execution snapshot frozen when this block target was chosen."""
        locked = self.locked_target_snapshots.get(sid) or {}
        snapshot = locked.get("snapshot")

        if (
            not snapshot
            or int(locked.get("digit", -1)) != int(digit)
        ):
            snapshot = self._score_all_digits(sid)

        row = None
        for item in snapshot.get("ranking") or []:
            if int(item.get("digit", -1)) == int(digit):
                row = dict(item)
                break

        shadow = snapshot.get("shadow") or {}
        shadow_row = None
        for item in shadow.get("ranking") or []:
            if int(item.get("digit", -1)) == int(shadow.get("selected_digit", -1)):
                shadow_row = dict(item)
                break

        return {
            "score_version": snapshot.get("version"),
            "history_count": snapshot.get("history_count"),
            "selected_digit": snapshot.get("selected_digit"),
            "top_margin": snapshot.get("top_margin"),
            "minimum_v1_margin": snapshot.get("minimum_v1_margin"),
            "margin_eligible": snapshot.get("margin_eligible"),
            "margin_status": snapshot.get("margin_status"),
            "excluded_digit": snapshot.get("excluded_digit"),
            "rank_seq": snapshot.get("rank_seq"),
            "rank_epoch": snapshot.get("rank_epoch"),
            "canonical_tick": snapshot.get("canonical_tick"),
            "candidate": row,
            "locked_target_digit": int(digit),
            "locked_at": locked.get("locked_at"),
            "shadow": {
                "version": shadow.get("version"),
                "selected_digit": shadow.get("selected_digit"),
                "selected_row": shadow_row,
                "dominance": shadow.get("dominance"),
                "break_digit_target": shadow.get("break_digit_target"),
                "alternating_pair_targets": shadow.get("alternating_pair_targets"),
            },
        }

    async def _bootstrap_digit_history(
        self,
        *,
        sid,
        symbol,
        client,
        count=100,
    ):
        """
        Rebuild the server-side DigitScore window from Deriv recent tick history.

        This is essential after a Render restart because TradingSession/TradeLog
        are persisted in PostgreSQL while digit_history is intentionally
        in-memory. Without this bootstrap the dashboard can show 0/10 even
        though the market has been running for hundreds of browser ticks.
        """
        sid = int(sid)
        history = self._digit_history(sid)
        minimum = int(getattr(self.digit_scorer, "min_history", 10) or 10)

        if len(history) >= minimum:
            return True

        generation = int(
            getattr(client, "connection_generation", 0) or 0
        )

        existing = self.history_bootstrap_tasks.get(sid)
        if existing and not existing.done():
            try:
                await asyncio.shield(existing)
            except Exception:
                pass
            return len(self._digit_history(sid)) >= minimum

        async def do_bootstrap():
            try:
                result = await client.ticks_history(
                    str(symbol),
                    count=max(50, int(count or 100)),
                )

                payload = result.get("history") or {}
                prices = list(payload.get("prices") or [])
                times = list(payload.get("times") or [])
                pip_size = result.get("pip_size")

                if not prices:
                    return False

                # Replace an incomplete process-local window with the canonical
                # recent history returned by Deriv, preserving chronological order.
                rebuilt = deque(maxlen=100)

                usable_times = len(times) == len(prices)
                last_epoch = 0

                for idx, price in enumerate(prices[-100:]):
                    tick = {
                        "quote": price,
                    }
                    if pip_size is not None:
                        tick["pip_size"] = pip_size

                    digit = self._tick_last_digit(tick)
                    if digit is None:
                        continue

                    rebuilt.append(int(digit))

                    if usable_times:
                        try:
                            epoch = int(times[-len(prices[-100:]) + idx])
                            last_epoch = max(last_epoch, epoch)
                        except Exception:
                            pass

                if not rebuilt:
                    return False

                self.digit_history[sid] = rebuilt

                if last_epoch:
                    self.latest_tick_epoch[sid] = max(
                        int(self.latest_tick_epoch.get(sid) or 0),
                        int(last_epoch),
                    )
                    if not hasattr(self, "_last_scored_epoch"):
                        self._last_scored_epoch = {}
                    self._last_scored_epoch[sid] = max(
                        int(self._last_scored_epoch.get(sid) or 0),
                        int(last_epoch),
                    )

                snapshot = self._score_all_digits(sid)

                if snapshot.get("ready"):
                    selected = snapshot.get("selected_digit")
                    if selected is not None:
                        self._set_live_next_target(
                            sid,
                            int(selected),
                        )

                self.history_bootstrap_generation[sid] = generation

                logger.warning(
                    "DMS DigitScore history bootstrapped sid=%s symbol=%s "
                    "ticks=%s ready=%s",
                    sid,
                    symbol,
                    len(rebuilt),
                    bool(snapshot.get("ready")),
                )

                return bool(snapshot.get("ready"))

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "DMS DigitScore history bootstrap failed sid=%s symbol=%s",
                    sid,
                    symbol,
                )
                return False

        task = asyncio.create_task(do_bootstrap())
        self.history_bootstrap_tasks[sid] = task

        try:
            return bool(await task)
        finally:
            current = self.history_bootstrap_tasks.get(sid)
            if current is task:
                self.history_bootstrap_tasks.pop(sid, None)

    async def _ensure_tick_subscription(
        self,
        *,
        sid,
        user_id,
        account_id,
        symbol,
        client,
    ):
        # Warm canonical server scoring immediately after process restart.
        # This does not place a trade; it only fetches public market history.
        if len(self._digit_history(int(sid))) < int(self.digit_scorer.min_history):
            await self._bootstrap_digit_history(
                sid=int(sid),
                symbol=str(symbol),
                client=client,
                count=100,
            )

        existing = self.tick_subscriptions.get(sid)

        healthy = bool(
            existing
            and existing.get("symbol") == str(symbol)
            and existing.get("client") is client
            and client.is_open()
            and (
                time.monotonic() - self.latest_tick_received_at.get(sid, time.monotonic())
            ) < 15.0
        )
        if healthy:
            return

        if existing:
            old_id = existing.get("subscription_id")
            old_client = existing.get("client")
            if old_id and old_client and old_client.is_open():
                asyncio.create_task(
                    self._forget_quietly(old_client, old_id)
                )
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
            "client": client,
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

        # Cache the selected market's precision from live server ticks.
        # Later callbacks may omit pip_size; the fallback prevents values such
        # as 86.700 from being interpreted as digit 7 instead of digit 0.
        live_decimals = self._pip_decimals(tick.get("pip_size"))
        if live_decimals is not None:
            self.tick_precision[int(sid)] = int(live_decimals)

        # Replayed cached ticks already carry _dms_seq and MUST NOT allocate
        # a second market sequence number. Only a genuinely new websocket
        # callback advances tick_sequence.
        existing_seq = int(tick.get("_dms_seq") or 0) if tick else 0
        current_seq = int(self.tick_sequence.get(sid, 0))

        if tick and existing_seq:
            tick_seq = int(existing_seq)
            if tick_seq > current_seq:
                self.tick_sequence[sid] = tick_seq
            is_replay = True
        elif tick:
            tick_seq = current_seq + 1
            self.tick_sequence[sid] = tick_seq
            tick["_dms_seq"] = int(tick_seq)
            self.latest_tick_received_at[sid] = time.monotonic()
            is_replay = False
        else:
            tick_seq = current_seq
            is_replay = False

        epoch = int(tick.get("epoch") or 0)

        # Only a new market callback may replace latest_ticks.
        if tick and not is_replay:
            cached = dict(tick)
            cached["_dms_seq"] = int(tick_seq)
            self.latest_ticks[sid] = cached

        if epoch:
            previous_epoch = int(self.latest_tick_epoch.get(sid) or 0)
            self.latest_tick_epoch[sid] = max(previous_epoch, epoch)

        digit = self._tick_last_digit(tick)
        if digit is not None:
            history = self._digit_history(sid)

            if not hasattr(self, "_last_scored_seq"):
                self._last_scored_seq = {}

            last_scored_seq = int(self._last_scored_seq.get(sid, 0))

            # Score each real market sequence exactly once.
            if (
                not is_replay
                and (not tick_seq or tick_seq > last_scored_seq)
            ):
                history.append(int(digit))
                if tick_seq:
                    self._last_scored_seq[sid] = int(tick_seq)

                live_snapshot = self._score_all_digits(sid)
                if live_snapshot.get("ready"):
                    self._set_live_next_target(
                        sid,
                        live_snapshot.get("selected_digit"),
                    )

        active = self.fast_contracts.get(sid)

        if not active:
            return

        if str(active.get("symbol")) != str(symbol):
            return

        if active.get("decided"):
            return

        armed_after_seq = int(active.get("armed_after_seq") or 0)
        incoming_seq = int(tick.get("_dms_seq") or tick_seq or 0)
        armed_after_epoch = int(active.get("armed_after_epoch") or 0)

        # Primary next-tick gate: exact callback sequence.
        # This accepts the very next tick even when it shares the same
        # whole-second epoch as the purchase/previous tick.
        if armed_after_seq and incoming_seq and incoming_seq <= armed_after_seq:
            return

        # Fallback only for legacy/cached messages that do not carry a sequence.
        if (
            not incoming_seq
            and epoch
            and armed_after_epoch
            and epoch <= armed_after_epoch
        ):
            return

        if digit is None:
            return

        # Mark synchronously before any await. Duplicate tick callbacks cannot
        # advance this same contract twice.
        active["decided"] = True
        active["decision_epoch"] = epoch
        active["decision_seq"] = incoming_seq
        active["observed_digit"] = digit

        target_digit = int(active["target_digit"])
        contract_id = str(active["contract_id"])
        is_win = digit == target_digit

        active["fast_result"] = "WIN" if is_win else "LOSS"

        execution_state = self.execution_contract_state.get(int(sid))
        if (
            isinstance(execution_state, dict)
            and str(execution_state.get("contract_id") or "") == contract_id
        ):
            execution_state["decision_seq"] = int(incoming_seq or 0) or None
            execution_state["decision_epoch"] = int(epoch or 0) or None
            execution_state["decision_digit"] = int(digit)
            execution_state["local_result"] = "WIN" if is_win else "LOSS"
            execution_state["decided"] = True
            execution_state["decision_source"] = "SERVER_MARKET_TICK"
            self.execution_contract_state[int(sid)] = execution_state

            snapshot = self.digit_score_snapshots.get(int(sid))
            if isinstance(snapshot, dict):
                snapshot["execution_contract"] = json.loads(
                    json.dumps(execution_state)
                )

        async with self._lock(sid):
            db = SessionLocal()

            try:
                s = db.get(TradingSession, sid)
                if not s:
                    return

                current_fast = self.fast_contracts.get(sid)

                # A callback from an older contract is not allowed to drive a
                # newer contract.
                if (
                    not current_fast
                    or str(current_fast.get("contract_id")) != contract_id
                ):
                    return

                if is_win:
                    # MATCH: target == exact strategy tick last digit.
                    #
                    # Stop immediately. Do not wait for official settlement.
                    # Settlement remains active in the background.
                    s.running = False
                    s.paused = False
                    s.pending_real_confirmation = False
                    s.phase = "FAST_WON"
                    self.locked_target_snapshots.pop(sid, None)
                    s.last_error = None
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                # NO MATCH: immediate local strategy LOSS.
                #
                # This is the point where the next recovery advances. Official
                # Deriv settlement of Trade N is NOT awaited.
                if int(s.current_trade) >= int(s.max_trades):
                    s.running = False
                    s.pending_real_confirmation = False
                    s.phase = "MAX_TRADES_REACHED"
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                # LIVE V1 RECOVERY:
                # the purchased contract remains fixed. After its loss, use the
                # freshest current V1 rank #1 for the next account-bound BUY.
                expected_trade_no = int(s.current_trade) + 1
                expected_stake = round(
                    float(s.current_stake) * float(s.multiplier),
                    2,
                )

                # The 0-9 cache was warmed while the current contract was open.
                # Selection happens AFTER this decision tick is scored, so the
                # freshest live V1 rank #1 can be bought without requesting a
                # new proposal on the critical path.
                payload = None

                # The latest V1 rank #1 is the authoritative NEXT target,
                # but it is executable only when the V1 margin gate is open.
                current_snapshot = self._score_all_digits(sid)
                margin_ok = bool(current_snapshot.get("margin_eligible"))

                if not margin_ok:
                    s.current_stake = expected_stake
                    s.phase = "RECOVERY_WAITING_MARGIN"
                    s.last_error = None
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                desired_next, current_snapshot = self._choose_scored_digit(
                    sid,
                    lock_target=True,
                )
                if desired_next is not None:
                    self._set_live_next_target(
                        sid,
                        desired_next,
                    )

                if desired_next is not None:
                    next_digit = int(desired_next)
                    old_digit = int(s.candidate_digit)
                    s.candidate_digit = next_digit
                    s.phase = (
                        f"LIVE_RANK_SWITCH_{old_digit}_TO_{next_digit}"
                        if next_digit != old_digit
                        else f"LIVE_RANK_KEEP_{next_digit}"
                    )
                    s.updated_at = datetime.utcnow()
                    db.commit()

                s.current_stake = expected_stake
                s.phase = "FAST_RECOVERING"
                s.updated_at = datetime.utcnow()
                db.commit()

                client = await self._client(user_id, account_id)
                currency = await self._currency_for(db, s)

                # Direct-parameter BUY: the selected V1 rank #1 can be used
                # immediately without waiting for a proposal ID.
                payload = self._direct_buy_payload(
                    symbol=s.symbol,
                    digit=int(s.candidate_digit),
                    stake=float(s.current_stake),
                    trade_no=expected_trade_no,
                    currency=currency,
                )

                s.phase = "DIRECT_BUY_READY"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()

                # LOSS -> immediate next BUY.
                #
                # No proposal_open_contract.is_sold wait occurs here.
                client = await self._client(user_id, account_id)

                await self._execute_account_buy(
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

    @staticmethod
    def _explicit_missing_contract_error(exc) -> bool:
        """
        Return True only for errors that explicitly indicate Deriv cannot
        resolve the supplied contract id. Generic auth/network/timeouts are
        NOT treated as safe-to-clear conditions.
        """
        message = str(exc or "").lower()
        needles = (
            "contractnotfound",
            "invalidcontract",
            "invalid contract",
            "unknown contract",
            "contract does not exist",
            "contract doesn't exist",
            "contract id not found",
            "contract_id not found",
        )
        return any(token in message for token in needles)

    def _contract_log_age_seconds(self, db, sid: int, contract_id: str):
        log = (
            db.query(TradeLog)
            .filter(
                TradeLog.trading_session_id == int(sid),
                TradeLog.contract_id == str(contract_id),
            )
            .order_by(TradeLog.id.desc())
            .first()
        )
        if not log or not getattr(log, "created_at", None):
            return None, log
        try:
            age = (datetime.utcnow() - log.created_at).total_seconds()
        except Exception:
            age = None
        return age, log

    async def _recover_stale_demo_contract(
        self,
        *,
        sid,
        contract_id,
        reason,
        minimum_age_seconds=15.0,
    ):
        """
        Release ONLY a stale DEMO 1-tick contract.

        Safety conditions:
        - session still points at this exact contract id;
        - account mode is DEMO;
        - matching persisted TradeLog exists;
        - contract is not already SETTLED;
        - persisted contract is old enough that a 1-tick contract cannot
          reasonably still be active.

        This deliberately never clears REAL state.
        """
        async with self._lock(int(sid)):
            db = SessionLocal()
            try:
                s = db.get(TradingSession, int(sid))
                if not s:
                    return False

                if str(s.account_mode or "").upper() != "DEMO":
                    return False

                if str(s.open_contract_id or "") != str(contract_id):
                    return False

                age, log = self._contract_log_age_seconds(
                    db,
                    int(sid),
                    str(contract_id),
                )

                if not log:
                    # Without persisted BUY evidence we cannot prove enough
                    # about the contract to clear it automatically.
                    return False

                if str(log.status or "").upper() == "SETTLED":
                    return False

                if age is None or float(age) < float(minimum_age_seconds):
                    return False

                # Preserve forensic evidence instead of deleting the trade.
                try:
                    raw = json.loads(log.raw_json or "{}")
                    if not isinstance(raw, dict):
                        raw = {"previous_raw": raw}
                except Exception:
                    raw = {"previous_raw_text": log.raw_json}

                raw["stale_demo_recovery"] = {
                    "contract_id": str(contract_id),
                    "reason": str(reason),
                    "age_seconds": float(age),
                    "recovered_at": datetime.utcnow().isoformat(),
                    "instance_id": self.instance_id,
                }
                log.raw_json = json.dumps(raw)
                log.status = "STALE_RECONCILED"

                # Release only this exact persisted owner.
                self.fast_contracts.pop(int(sid), None)
                self.retired_fast_contracts.pop(
                    (int(sid), str(contract_id)),
                    None,
                )

                key = (int(sid), str(contract_id))
                self.contract_probe_unsold.pop(key, None)
                self.contract_probe_errors.pop(key, None)
                self.contract_probe_at.pop(key, None)

                poll = self.contract_poll_tasks.pop(key, None)
                if poll and poll is not asyncio.current_task() and not poll.done():
                    poll.cancel()

                sub_id = self.contract_subscriptions.pop(key, None)
                client = self.clients.get((s.user_id, s.account_id))
                if client and sub_id:
                    asyncio.create_task(
                        self._forget_quietly(client, sub_id)
                    )

                # Start a clean DEMO cycle. We do not pretend that the stale
                # contract settled or add fabricated P/L.
                s.open_contract_id = None
                s.pending_trade_json = None
                s.pending_real_confirmation = False
                s.current_trade = 0
                s.current_stake = float(s.base_stake or 1.0)
                s.pnl = 0.0
                s.running = True
                s.paused = False
                s.phase = "STALE_DEMO_CONTRACT_CLEARED"
                s.last_error = (
                    "Recovered stale DEMO contract "
                    f"{contract_id}: {reason}"
                )
                s.updated_at = datetime.utcnow()
                db.commit()

                logger.warning(
                    "DMS stale DEMO contract cleared sid=%s contract=%s "
                    "age=%.1fs reason=%s",
                    sid,
                    contract_id,
                    float(age),
                    reason,
                )
                return True
            finally:
                db.close()

    def _schedule_contract_probe(
        self,
        *,
        sid,
        user_id,
        account_id,
        contract_id,
        client,
        urgent=False,
    ):
        """
        Schedule one authoritative reconciliation check without waiting under
        the session lock.

        Normal settlement still wins. Stale release is DEMO-only and bounded.

        When the in-memory fast owner is missing, urgent=True shortens the
        reconciliation cadence for the outstanding 1-tick contract. This does
        NOT invent a local next-tick result after a process restart; it only
        asks Deriv for the authoritative sold state sooner, then the normal
        recovery path resumes from persisted TradeLog evidence.

        The urgent interval backs off automatically after unsold responses or
        transport errors so a reconnect problem cannot hammer Deriv.
        """
        key = (int(sid), str(contract_id))
        task = self.contract_probe_tasks.get(key)
        if task and not task.done():
            return

        now = time.monotonic()

        if urgent:
            unsold_count = int(self.contract_probe_unsold.get(key, 0) or 0)
            error_count = int(self.contract_probe_errors.get(key, 0) or 0)

            # First recovery check is near-immediate, then progressively backs
            # off while the contract remains unresolved.
            unsold_delay = min(1.50, 0.45 + (0.25 * unsold_count))
            error_delay = min(
                2.00,
                0.45 * (2 ** min(error_count, 3)),
            )
            probe_interval = max(unsold_delay, error_delay)
        else:
            probe_interval = 3.0

        if now - self.contract_probe_at.get(key, 0) < probe_interval:
            return
        self.contract_probe_at[key] = now

        async def probe():
            try:
                result = await client.contract_status(str(contract_id))
                poc = result.get("proposal_open_contract") or {}

                if poc.get("is_sold"):
                    self.contract_probe_unsold.pop(key, None)
                    self.contract_probe_errors.pop(key, None)
                    logger.warning(
                        "DMS authoritative settlement recovered "
                        "sid=%s contract=%s",
                        sid,
                        contract_id,
                    )
                    await self._handle_contract_update(
                        sid=sid,
                        user_id=user_id,
                        account_id=account_id,
                        contract_id=str(contract_id),
                        data=result,
                    )
                    return

                # Successful response, but still not sold. For a 1-tick DEMO
                # contract this cannot continue indefinitely after restart.
                count = int(self.contract_probe_unsold.get(key, 0)) + 1
                self.contract_probe_unsold[key] = count

                db = SessionLocal()
                try:
                    age, _log = self._contract_log_age_seconds(
                        db,
                        int(sid),
                        str(contract_id),
                    )
                finally:
                    db.close()

                # Require several successful authoritative probes AND age >30s.
                # This prevents a normal newly purchased contract being cleared.
                if (
                    count >= 5
                    and age is not None
                    and float(age) >= 30.0
                ):
                    await self._recover_stale_demo_contract(
                        sid=sid,
                        contract_id=str(contract_id),
                        reason=(
                            "Deriv continued to report a 1-tick contract "
                            f"as unsold after {count} authoritative probes"
                        ),
                        minimum_age_seconds=30.0,
                    )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                count = int(self.contract_probe_errors.get(key, 0)) + 1
                self.contract_probe_errors[key] = count

                logger.exception(
                    "DMS contract reconciliation failed sid=%s contract=%s",
                    sid,
                    contract_id,
                )

                # Only explicit missing/invalid-contract responses are eligible
                # for fast stale recovery. Generic WebSocket/auth/timeouts stay
                # locked for safety and are retried on the next worker pass.
                if self._explicit_missing_contract_error(exc):
                    await self._recover_stale_demo_contract(
                        sid=sid,
                        contract_id=str(contract_id),
                        reason=f"Deriv rejected persisted contract: {exc}",
                        minimum_age_seconds=15.0,
                    )

            finally:
                self.contract_probe_tasks.pop(key, None)

        self.contract_probe_tasks[key] = asyncio.create_task(probe())

    async def step(self, sid: int):
        async with self._lock(sid):
            db = SessionLocal()

            try:
                s = db.get(TradingSession, sid)

                if not s or not s.running or s.paused:
                    return

                # Explicit Deriv RateLimit means no contract was purchased.
                # Hold the SAME logical next trade/stake until the cooldown
                # expires. This prevents the 20ms worker loop from immediately
                # re-entering BUY and extending the throttle.
                rate_until = float(
                    self.buy_rate_limit_until.get(int(sid), 0.0) or 0.0
                )
                now_mono = time.monotonic()
                if rate_until > now_mono:
                    s.phase = "BUY_RATE_LIMIT_BACKOFF"
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return
                elif rate_until:
                    self.buy_rate_limit_until.pop(int(sid), None)

                if s.last_error:
                    # Clear ordinary stale errors once the worker is healthy.
                    # Keep reconciliation mismatches visible.
                    if "mismatch" not in str(s.last_error).lower():
                        s.last_error = None
                        db.commit()

                client = await self._client(
                    s.user_id,
                    s.account_id,
                )

                await self._ensure_tick_subscription(
                    sid=s.id,
                    user_id=s.user_id,
                    account_id=s.account_id,
                    symbol=s.symbol,
                    client=client,
                )

                # Reconcile persisted contract state BEFORE attempting a new buy.
                # Never release ownership purely because a feed is stale.
                latest = (
                    db.query(TradeLog)
                    .filter(
                        TradeLog.trading_session_id == sid,
                        TradeLog.trade_no == s.current_trade,
                    )
                    .order_by(TradeLog.id.desc())
                    .first()
                ) if s.current_trade else None

                fast_owner = self.fast_contracts.get(sid)

                # A freshly configured/restarted cycle at trade 0 cannot own a
                # previously purchased in-memory contract. If persistent state
                # says there is no open contract, retire that stale process-local
                # owner so it cannot strand the new cycle in
                # FAST_DECISION_APPLYING.
                if (
                    int(s.current_trade or 0) == 0
                    and not s.open_contract_id
                    and fast_owner
                ):
                    stale_contract_id = str(
                        fast_owner.get("contract_id") or ""
                    )
                    self.fast_contracts.pop(sid, None)
                    if stale_contract_id:
                        self.retired_fast_contracts.pop(
                            (int(sid), stale_contract_id),
                            None,
                        )
                    fast_owner = None

                contract_id = str(
                    s.open_contract_id
                    or (fast_owner or {}).get("contract_id")
                    or (latest.contract_id if latest else "")
                    or ""
                )

                if latest and contract_id and str(latest.contract_id) != contract_id:
                    s.running = False
                    s.phase = "RECOVERY_CONTRACT_MISMATCH"
                    s.last_error = "Active contract does not match the persisted trade log"
                    db.commit()
                    return

                # ----------------------------------------------------------
                # SHARED ACCOUNT PIPELINE IS TICK-OWNED, NOT SETTLEMENT-OWNED
                # ----------------------------------------------------------
                # While this process still owns the active paid contract,
                # the first eligible NEXT market tick drives WIN/LOSS and
                # immediate recovery. Deriv settlement remains background-only.
                if (
                    fast_owner
                    and contract_id
                    and str(fast_owner.get("contract_id") or "") == contract_id
                ):
                    if not latest or str(latest.status).upper() != "SETTLED":
                        self._schedule_contract_probe(
                            sid=sid,
                            user_id=s.user_id,
                            account_id=s.account_id,
                            contract_id=contract_id,
                            client=client,
                        )
                        contract_key = (sid, contract_id)
                        if contract_key not in self.contract_subscriptions:
                            asyncio.create_task(
                                self._subscribe_open_contract(
                                    sid=sid,
                                    user_id=s.user_id,
                                    account_id=s.account_id,
                                    contract_id=contract_id,
                                    client=client,
                                )
                            )

                    s.phase = (
                        "FAST_DECISION_APPLYING"
                        if fast_owner.get("decided")
                        else "AWAITING_NEXT_TICK"
                    )
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                # No live in-memory owner means restart/recovery state.
                # We cannot safely recreate a missed "first tick after BUY"
                # across a process restart because callback sequence continuity
                # is gone. Instead, switch to fast authoritative reconciliation:
                # ask Deriv for the sold state on a sub-second/backoff cadence,
                # then resume immediately from the persisted settlement.
                if contract_id and (not latest or str(latest.status).upper() != "SETTLED"):
                    # Subscription is best effort; bounded authoritative polling
                    # continues even if a subscription ID exists but stopped firing.
                    self._schedule_contract_probe(
                        sid=sid, user_id=s.user_id,
                        account_id=s.account_id, contract_id=contract_id,
                        client=client,
                        urgent=True,
                    )
                    contract_key = (sid, contract_id)
                    if contract_key not in self.contract_subscriptions:
                        asyncio.create_task(
                            self._subscribe_open_contract(
                                sid=sid, user_id=s.user_id,
                                account_id=s.account_id,
                                contract_id=contract_id, client=client,
                            )
                        )
                    probe_key = (int(sid), str(contract_id))
                    probe_count = int(
                        self.contract_probe_unsold.get(probe_key, 0)
                    )
                    error_count = int(
                        self.contract_probe_errors.get(probe_key, 0)
                    )
                    if probe_count or error_count:
                        s.phase = (
                            "WAITING_OFFICIAL_SETTLEMENT"
                            f"_P{probe_count}_E{error_count}"
                        )
                    else:
                        s.phase = "WAITING_OFFICIAL_SETTLEMENT"
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                if latest and str(latest.status).upper() == "SETTLED":
                    if latest.profit is None:
                        s.running = False
                        s.phase = "RECOVERY_MISSING_PROFIT"
                        s.last_error = "SETTLED trade log has no authoritative profit"
                        db.commit()
                        return
                    official_result = "WIN" if float(latest.profit) > 0 else "LOSS"
                    if fast_owner and fast_owner.get("fast_result") and fast_owner["fast_result"] != official_result:
                        s.running = False
                        s.phase = "RECONCILE_MISMATCH"
                        s.last_error = "Fast result disagrees with official Deriv settlement"
                        db.commit()
                        return
                    if official_result == "WIN":
                        s.running = False
                        s.phase = "WON"
                        self.fast_contracts.pop(sid, None)
                        s.open_contract_id = None
                        db.commit()
                        return
                    # Official LOSS: clear only this exact completed owner.
                    if fast_owner and str(fast_owner.get("contract_id")) == str(latest.contract_id):
                        self.fast_contracts.pop(sid, None)
                    if str(s.open_contract_id or "") == str(latest.contract_id):
                        s.open_contract_id = None
                    expected_stake = round(float(latest.stake) * float(s.multiplier), 2)
                    if float(s.current_stake or 0) < expected_stake - 0.005:
                        s.current_stake = expected_stake
                    fresh_digit, snapshot = self._choose_scored_digit(sid, lock_target=True)
                    if fresh_digit is None:
                        s.phase = (
                            "RECOVERY_WAITING_MARGIN"
                            if snapshot.get("ready") and not snapshot.get("margin_eligible")
                            else "RECOVERY_WAITING_RANK"
                        )
                        s.updated_at = datetime.utcnow()
                        db.commit()
                        return
                    s.candidate_digit = int(fresh_digit)
                    self._set_live_next_target(sid, int(fresh_digit))
                    s.phase = "RECOVERY_READY"
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    # Fall through to the existing proposal/BUY claim path.
                elif int(s.current_trade or 0) > 0:
                    s.running = False
                    s.phase = "RECOVERY_MISSING_TRADE_LOG"
                    s.last_error = "Cannot verify previous purchase in trade log"
                    db.commit()
                    return

                if s.current_trade >= s.max_trades:
                    s.running = False
                    s.phase = "MAX_TRADES_REACHED"
                    db.commit()
                    return

                if int(s.current_trade) == 0:
                    scored_digit, snapshot = self._choose_scored_digit(s.id, lock_target=True)
                    if scored_digit is None:
                        if snapshot.get("ready") and not snapshot.get("margin_eligible"):
                            s.phase = "WAITING_V1_MARGIN"
                            s.last_error = None
                        else:
                            s.phase = "DIGIT_SCORE_WARMING"
                            s.last_error = (
                                "Scoring digits 0-9 from canonical ticks "
                                f"({snapshot.get('history_count', 0)}/"
                                f"{snapshot.get('minimum_history', 10)}). "
                                "Deriv history bootstrap/live feed is warming."
                            )
                        s.updated_at = datetime.utcnow()
                        db.commit()
                        return
                    s.candidate_digit = int(scored_digit)
                    self._set_live_next_target(
                        s.id,
                        int(scored_digit),
                    )
                    s.last_error = None
                    s.phase = "DIGIT_SCORE_READY"
                    s.updated_at = datetime.utcnow()
                    db.commit()

                if s.candidate_digit is None:
                    s.phase = "WAITING_CANDIDATE"
                    db.commit()
                    return

                currency = await self._currency_for(db, s)

                # First trade uses the freshest V1 rank #1 and buys
                # directly from parameters. No proposal request/cache is needed.
                scored_digit, snapshot = self._choose_scored_digit(
                    s.id,
                    lock_target=True,
                )
                if scored_digit is None:
                    s.phase = (
                        "WAITING_V1_MARGIN"
                        if snapshot.get("ready") and not snapshot.get("margin_eligible")
                        else "DIGIT_SCORE_WARMING"
                    )
                    s.last_error = None
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                s.candidate_digit = int(scored_digit)
                self._set_live_next_target(
                    s.id,
                    int(scored_digit),
                )

                s.phase = "DIRECT_BUY_READY"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()

                payload = self._direct_buy_payload(
                    symbol=s.symbol,
                    digit=int(s.candidate_digit),
                    stake=float(s.current_stake),
                    trade_no=int(s.current_trade) + 1,
                    currency=currency,
                )

                await self._execute_account_buy(
                    db,
                    s,
                    client,
                    payload,
                    prearmed=False,
                )

            finally:
                db.close()

    @staticmethod
    def _pending_json(value):
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _claim_account_buy(self, db, sid: int, payload: dict):
        """
        Atomically claim one BUY through the shared database.

        Python asyncio locks only protect one process. PostgreSQL row locking +
        a persisted claim prevents a second Render process from buying the same
        logical trade number during overlapping deploys/restarts.
        """
        row = (
            db.query(TradingSession)
            .filter(TradingSession.id == int(sid))
            .with_for_update()
            .one_or_none()
        )

        if not row or not row.running or row.paused:
            db.rollback()
            return None

        trade_no = int(payload.get("trade_no") or 0)
        digit = int(payload.get("digit"))
        stake = round(float(payload.get("stake") or 0), 2)
        expected_trade_no = int(row.current_trade or 0) + 1

        # STRICT V1 MARGIN GATE — final authoritative pre-BUY barrier.
        # A target may have qualified a fraction of a second earlier and then
        # lost its lead on a newer tick before the network BUY was sent.
        # Re-score HERE, immediately before claiming the paid purchase.
        gate_snapshot = self._score_all_digits(int(sid))
        gate_margin = gate_snapshot.get("top_margin")
        gate_minimum = self.get_minimum_v1_margin(int(sid))
        gate_top = gate_snapshot.get("selected_digit")
        gate_ok = bool(
            gate_snapshot.get("ready")
            and gate_snapshot.get("margin_eligible")
            and gate_top is not None
            and int(gate_top) == int(digit)
        )

        if not gate_ok:
            row.pending_trade_json = None
            row.running = True
            row.paused = False
            row.phase = (
                "RECOVERY_WAITING_MARGIN"
                if int(row.current_trade or 0) > 0
                else "WAITING_V1_MARGIN"
            )
            row.candidate_digit = (
                int(gate_top) if gate_top is not None else row.candidate_digit
            )
            row.last_error = None
            row.updated_at = datetime.utcnow()
            db.commit()
            return None

        # Freeze the exact gate evidence used to authorize this BUY.
        payload["margin_gate"] = {
            "top_margin": float(gate_margin) if gate_margin is not None else None,
            "minimum_v1_margin": float(gate_minimum),
            "selected_digit": int(gate_top),
            "eligible": True,
            "rank_seq": gate_snapshot.get("rank_seq"),
            "rank_epoch": gate_snapshot.get("rank_epoch"),
            "checked_at": datetime.utcnow().isoformat(),
        }

        # A stale or competing continuation is never allowed to BUY.
        if trade_no != expected_trade_no:
            db.rollback()
            return None

        if row.candidate_digit is None or int(row.candidate_digit) != digit:
            db.rollback()
            return None

        if abs(float(row.current_stake or 0) - stake) > 0.005:
            db.rollback()
            return None

        pending = self._pending_json(row.pending_trade_json)

        # Another process already owns this exact BUY.
        if (
            pending.get("kind") == "BUY_CLAIM"
            and int(pending.get("trade_no") or 0) == trade_no
        ):
            db.rollback()
            return None

        claim_token = uuid.uuid4().hex

        row.pending_trade_json = json.dumps({
            "kind": "BUY_CLAIM",
            "token": claim_token,
            "trade_no": trade_no,
            "digit": digit,
            "stake": stake,
            "instance_id": self.instance_id,
            "claimed_at": datetime.utcnow().isoformat(),
        })
        row.phase = f"BUY_CLAIMED_{trade_no}"
        row.updated_at = datetime.utcnow()
        db.commit()

        return {
            "token": claim_token,
            "trade_no": trade_no,
            "digit": digit,
            "stake": stake,
            "instance_id": self.instance_id,
        }

    def _claim_is_owned(self, row, claim: dict) -> bool:
        pending = self._pending_json(row.pending_trade_json)
        return bool(
            pending.get("kind") == "BUY_CLAIM"
            and pending.get("token") == claim.get("token")
            and int(pending.get("trade_no") or 0)
            == int(claim.get("trade_no") or 0)
        )

    async def _execute_account_buy(
        self,
        db,
        s,
        client,
        payload,
        *,
        prearmed: bool,
        rate_retry_used: bool = False,
    ):
        account_mode = str(s.account_mode or "").upper()
        if account_mode not in {"DEMO", "REAL"}:
            raise RuntimeError(
                f"Automated purchase blocked for unsupported account mode {account_mode!r}"
            )
        if account_mode == "REAL" and not settings.allow_real_mode:
            raise RuntimeError(
                "REAL trading is disabled; set ALLOW_REAL_MODE=true to enable it"
            )

        # ------------------------------------------------------------------
        # DATABASE BUY CLAIM
        # ------------------------------------------------------------------
        # This is the cross-process idempotency barrier. Every code path,
        # including Trade 1, recovery, recycle and fallback, must pass here.
        claim = self._claim_account_buy(db, s.id, payload)

        if not claim:
            # Another process/path already owns or advanced this logical trade.
            # Do not BUY, do not mutate the shared session, do not increment
            # stake/trade number.
            return False

        # Refresh after the claim commit so all following state is canonical.
        s = db.get(TradingSession, s.id)

        await self._ensure_tick_subscription(
            sid=s.id,
            user_id=s.user_id,
            account_id=s.account_id,
            symbol=s.symbol,
            client=client,
        )

        # Do not replace BUY_CLAIMED_* before the network call; the claim must
        # remain visible to every competing server process.
        s.updated_at = datetime.utcnow()
        db.commit()

        buy_sent_after_epoch = int(
            self.latest_tick_epoch.get(s.id) or 0
        )
        buy_sent_after_seq = int(
            self.tick_sequence.get(s.id, 0)
        )

        execution_mode = str(
            payload.get("execution_mode") or "PROPOSAL_ID"
        ).upper()

        # Legacy proposal IDs can become invalid across a reconnect. Direct
        # parameter BUY has no proposal-generation dependency.
        if execution_mode != "DIRECT_PARAMETERS":
            proposal_generation = int(payload.get("connection_generation") or 0)
            current_generation = int(
                getattr(client, "connection_generation", 0) or 0
            )
            if (
                proposal_generation
                and current_generation
                and proposal_generation != current_generation
            ):
                payload = await self._request_proposal_payload(
                    client,
                    symbol=s.symbol,
                    digit=int(payload["digit"]),
                    stake=float(payload["stake"]),
                    trade_no=int(payload["trade_no"]),
                    currency=str(payload.get("currency") or "USD"),
                )

        try:
            if execution_mode == "DIRECT_PARAMETERS":
                result = await client.buy_digitmatch_direct(
                    symbol=s.symbol,
                    digit=int(payload["digit"]),
                    amount=float(payload["stake"]),
                    currency=str(payload.get("currency") or "USD"),
                    duration=1,
                    account_mode=account_mode,
                )
            else:
                result = await client.buy(
                    payload["proposal_id"],
                    payload["ask_price"],
                    account_mode=account_mode,
                )
        except Exception as exc:
            text = str(exc).lower()

            # RateLimit is an explicit rejection, not an ambiguous timeout:
            # no contract was purchased. Release the exact BUY claim.
            if "ratelimit" in text or "rate limit" in text:
                row = (
                    db.query(TradingSession)
                    .filter(TradingSession.id == int(s.id))
                    .with_for_update()
                    .one_or_none()
                )

                if row and self._claim_is_owned(row, claim):
                    row.pending_trade_json = None
                    row.running = True
                    row.paused = False
                    row.phase = "BUY_RATE_LIMIT_BACKOFF"
                    row.last_error = (
                        f"BUY_RATE_LIMIT trade {claim['trade_no']}: {exc}"
                    )
                    row.updated_at = datetime.utcnow()
                    db.commit()

                # The previous trade has already been decided locally. Move it
                # out of the active strategy slot so it cannot strand the
                # session in FAST_DECISION_APPLYING while settlement catches up.
                prior = self.fast_contracts.get(int(s.id))
                if prior and prior.get("decided"):
                    prior_contract_id = str(prior.get("contract_id") or "")
                    if prior_contract_id:
                        self.retired_fast_contracts[
                            (int(s.id), prior_contract_id)
                        ] = dict(prior)
                    self.fast_contracts.pop(int(s.id), None)

                # Create a real cooldown barrier. Do NOT recurse into another
                # BUY here: the worker loop itself will resume the SAME logical
                # trade once the deadline expires, using the freshest V1 #1.
                sid_int = int(s.id)
                streak = min(
                    int(self.buy_rate_limit_streak.get(sid_int, 0)) + 1,
                    5,
                )
                self.buy_rate_limit_streak[sid_int] = streak

                backoff_table = (1.5, 2.5, 4.0, 6.0, 8.0)
                cooldown = float(backoff_table[streak - 1])
                self.buy_rate_limit_until[sid_int] = (
                    time.monotonic() + cooldown
                )

                row = db.get(TradingSession, sid_int)
                if row:
                    row.phase = "BUY_RATE_LIMIT_BACKOFF"
                    row.last_error = (
                        f"BUY_RATE_LIMIT trade {claim['trade_no']}: "
                        f"retry after {cooldown:.1f}s · {exc}"
                    )
                    row.updated_at = datetime.utcnow()
                    db.commit()

                return False

            # Explicit stale proposal rejection means no contract was bought.
            # Refresh once. Generic timeout/network errors remain non-retriable.
            stale_proposal = (
                "invalidcontractproposal" in text
                or "unknown contract proposal" in text
            )

            if stale_proposal and execution_mode != "DIRECT_PARAMETERS":
                try:
                    payload = await self._request_proposal_payload(
                        client,
                        symbol=s.symbol,
                        digit=int(payload["digit"]),
                        stake=float(payload["stake"]),
                        trade_no=int(payload["trade_no"]),
                        currency=str(payload.get("currency") or "USD"),
                    )
                    result = await client.buy(
                        payload["proposal_id"],
                        payload["ask_price"],
                        account_mode=account_mode,
                    )
                except Exception as retry_exc:
                    exc = retry_exc
                else:
                    exc = None

            if exc is not None:
                row = (
                    db.query(TradingSession)
                    .filter(TradingSession.id == int(s.id))
                    .with_for_update()
                    .one_or_none()
                )
                if row and self._claim_is_owned(row, claim):
                    row.running = False
                    row.paused = False
                    row.phase = "BUY_UNCERTAIN_STOPPED"
                    row.last_error = (
                        f"BUY_UNCERTAIN trade {claim['trade_no']}: {exc}"
                    )
                    row.updated_at = datetime.utcnow()
                    db.commit()
                raise RuntimeError(
                    f"BUY_UNCERTAIN trade {claim['trade_no']}: {exc}"
                ) from exc

        buy = result.get("buy") or {}

        if not buy.get("contract_id"):
            row = (
                db.query(TradingSession)
                .filter(TradingSession.id == int(s.id))
                .with_for_update()
                .one_or_none()
            )
            if row and self._claim_is_owned(row, claim):
                row.running = False
                row.phase = "BUY_UNCERTAIN_STOPPED"
                row.last_error = "BUY_UNCERTAIN: Deriv returned no contract_id"
                row.updated_at = datetime.utcnow()
                db.commit()
            raise RuntimeError(
                "BUY_UNCERTAIN: Deriv returned no contract_id; "
                f"keys={list(result.keys())}"
            )

        contract_id = str(buy["contract_id"])

        # A confirmed BUY proves the throttle window has cleared.
        self.buy_rate_limit_until.pop(int(s.id), None)
        self.buy_rate_limit_streak.pop(int(s.id), None)

        # Capture the callback sequence at BUY acknowledgement. If the market
        # advanced while the BUY request was in flight, we cannot prove which
        # of those ticks Deriv used for the 1-tick contract from market-stream
        # timing alone. In that rare case, do NOT falsely judge a later tick;
        # wait for authoritative contract settlement for this trade.
        buy_ack_seq = int(self.tick_sequence.get(s.id, 0))
        buy_ack_epoch = int(self.latest_tick_epoch.get(s.id) or 0)
        inflight_tick_count = max(
            0,
            int(buy_ack_seq) - int(buy_sent_after_seq),
        )
        official_only_inflight = inflight_tick_count > 0

        # Lock the row again and prove that this process still owns the exact
        # claim before committing the purchased contract into the cycle.
        row = (
            db.query(TradingSession)
            .filter(TradingSession.id == int(s.id))
            .with_for_update()
            .one_or_none()
        )

        if not row or not self._claim_is_owned(row, claim):
            # A BUY has happened, so never retry. Record a hard stop for manual
            # reconciliation rather than silently creating a second purchase.
            if row:
                row.running = False
                row.phase = "BUY_CLAIM_LOST"
                row.last_error = (
                    f"BUY_CLAIM_LOST trade {claim['trade_no']} "
                    f"contract {contract_id}"
                )
                row.updated_at = datetime.utcnow()
                db.commit()
            raise RuntimeError(
                f"BUY_CLAIM_LOST trade {claim['trade_no']} "
                f"contract {contract_id}"
            )

        # Re-check sequence under the same PostgreSQL row lock.
        if int(row.current_trade or 0) + 1 != int(claim["trade_no"]):
            row.running = False
            row.phase = "BUY_SEQUENCE_MISMATCH"
            row.last_error = (
                f"BUY_SEQUENCE_MISMATCH expected "
                f"{int(row.current_trade or 0) + 1}, "
                f"bought {claim['trade_no']} contract {contract_id}"
            )
            row.updated_at = datetime.utcnow()
            db.commit()
            raise RuntimeError(row.last_error)

        score_evidence = self._trade_score_evidence(
            row.id,
            int(payload["digit"]),
        )

        db.add(
            TradeLog(
                user_id=row.user_id,
                trading_session_id=row.id,
                trade_no=int(payload["trade_no"]),
                account_mode=row.account_mode,
                account_id=row.account_id,
                symbol=row.symbol,
                digit=int(payload["digit"]),
                stake=float(payload["stake"]),
                contract_id=contract_id,
                status="OPEN",
                buy_price=float(
                    buy.get("buy_price")
                    or payload["ask_price"]
                ),
                payout=(
                    float(buy.get("payout"))
                    if buy.get("payout") is not None
                    else payload.get("payout")
                ),
                raw_json=json.dumps({
                    "deriv_buy": result,
                    "dms_score_evidence": score_evidence,
                    "margin_gate": payload.get("margin_gate"),
                    "execution_integrity": {
                        "instance_id": self.instance_id,
                        "buy_claim_token": claim["token"],
                        "claimed_trade_no": claim["trade_no"],
                        "prearmed": bool(prearmed),
                        "buy_sent_after_seq": int(buy_sent_after_seq),
                        "buy_sent_after_epoch": int(buy_sent_after_epoch),
                        "buy_ack_seq": int(buy_ack_seq),
                        "buy_ack_epoch": int(buy_ack_epoch),
                        "inflight_tick_count": int(inflight_tick_count),
                        "arming_policy": (
                            "OFFICIAL_ONLY_INFLIGHT_TICK"
                            if official_only_inflight
                            else "FIRST_NEW_SERVER_TICK_AFTER_BUY_ACK"
                        ),
                    },
                }),
            )
        )

        purchase_epoch = int(
            buy.get("start_time")
            or buy.get("purchase_time")
            or buy_ack_epoch
            or 0
        )

        # Exact callback sequence is authoritative for local fast ownership.
        decision_after_epoch = max(
            buy_ack_epoch,
            purchase_epoch,
        )

        execution_state = {
            "contract_id": contract_id,
            "target_digit": int(payload["digit"]),
            "symbol": str(row.symbol),
            "trade_no": int(payload["trade_no"]),
            "buy_sent_after_seq": int(buy_sent_after_seq),
            "buy_sent_after_epoch": int(buy_sent_after_epoch),
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
        self.execution_contract_state[int(row.id)] = execution_state

        if official_only_inflight:
            self.fast_contracts.pop(int(row.id), None)
        else:
            self.fast_contracts[row.id] = {
                "contract_id": contract_id,
                "target_digit": int(payload["digit"]),
                "symbol": str(row.symbol),
                "trade_no": int(payload["trade_no"]),
                "armed_after_epoch": decision_after_epoch,
                "armed_after_seq": int(buy_ack_seq),
                "buy_sent_after_seq": int(buy_sent_after_seq),
                "buy_ack_seq": int(buy_ack_seq),
                "score_evidence": score_evidence,
                "buy_claim_token": claim["token"],
                "instance_id": self.instance_id,
                "decided": False,
            }

        snapshot = self.digit_score_snapshots.get(int(row.id))
        if isinstance(snapshot, dict):
            snapshot["execution_contract"] = json.loads(
                json.dumps(execution_state)
            )

        row.open_contract_id = contract_id
        row.phase = (
            "WAITING_OFFICIAL_SETTLEMENT_INFLIGHT_TICK"
            if official_only_inflight
            else "PIPELINE_ACTIVE"
        )
        row.current_trade = int(payload["trade_no"])
        row.pending_trade_json = None
        row.pending_real_confirmation = False
        row.last_error = None
        row.updated_at = datetime.utcnow()
        db.commit()

        # Rebind local reference after commit.
        s = db.get(TradingSession, row.id)

        # Direct-buy build: no per-trade proposal cache to rebuild.

        # Normal case: no market tick occurred while BUY was in flight, so
        # the first genuinely new server tick after BUY ACK can decide locally.
        # Ambiguous case: one or more in-flight ticks occurred; no fast owner
        # exists and step() waits for authoritative Deriv settlement instead.

        asyncio.create_task(
            self._subscribe_open_contract(
                sid=s.id,
                user_id=s.user_id,
                account_id=s.account_id,
                contract_id=contract_id,
                client=client,
            )
        )

        return True

    async def _subscribe_open_contract(
        self,
        *,
        sid,
        user_id,
        account_id,
        contract_id,
        client,
    ):
        key = (
            sid,
            str(contract_id),
        )

        if key in self.contract_subscriptions:
            return

        if key in self.contract_poll_tasks:
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

        # Fallback only if Deriv does not return a subscription id for the
        # very short-lived 1-tick contract. This runs in the background and
        # never gates strategy execution.
        async def poll_until_sold():
            try:
                for _ in range(150):
                    await asyncio.sleep(0.20)

                    data = await client.contract_status(
                        str(contract_id)
                    )

                    poc = (
                        data.get("proposal_open_contract")
                        or {}
                    )

                    await on_contract_update(data)

                    if poc.get("is_sold"):
                        return

            except asyncio.CancelledError:
                raise

            except Exception:
                # The trade remains visible as OPEN for later reconciliation.
                return

            finally:
                self.contract_poll_tasks.pop(
                    key,
                    None,
                )

        self.contract_poll_tasks[key] = asyncio.create_task(
            poll_until_sold()
        )

    def _authoritative_cycle_summary(self, db, log):
        """
        Return the exact Deriv-settled P/L for the cycle containing `log`.

        Cycle boundaries are reconstructed from persisted TradeLog trade_no
        resets. A summary becomes authoritative only when:
        - the cycle starts at trade_no 1,
        - every trade number through the winning/current trade exists once,
        - every row is SETTLED.

        This is used for Telegram so the message reports actual cycle profit/loss,
        not merely the final winning contract's profit.
        """
        if not log:
            return {
                "authoritative": False,
                "cycle_pnl": None,
                "cycle_stake": None,
                "cycle_trades": 0,
            }

        target_trade_no = int(log.trade_no or 0)
        if target_trade_no < 1:
            return {
                "authoritative": False,
                "cycle_pnl": None,
                "cycle_stake": None,
                "cycle_trades": 0,
            }

        previous_rows = (
            db.query(TradeLog)
            .filter(
                TradeLog.trading_session_id == int(log.trading_session_id),
                TradeLog.id <= int(log.id),
            )
            .order_by(TradeLog.id.desc())
            .all()
        )

        cycle_start_id = None
        for row in previous_rows:
            if int(row.trade_no or 0) == 1:
                cycle_start_id = int(row.id)
                break

        if cycle_start_id is None:
            return {
                "authoritative": False,
                "cycle_pnl": None,
                "cycle_stake": None,
                "cycle_trades": 0,
            }

        rows = (
            db.query(TradeLog)
            .filter(
                TradeLog.trading_session_id == int(log.trading_session_id),
                TradeLog.id >= cycle_start_id,
                TradeLog.id <= int(log.id),
            )
            .order_by(TradeLog.id.asc())
            .all()
        )

        # Exactly one persisted row for each logical trade number 1..N.
        by_trade = {}
        duplicate = False
        for row in rows:
            no = int(row.trade_no or 0)
            if no in by_trade:
                duplicate = True
            by_trade[no] = row

        expected = set(range(1, target_trade_no + 1))
        present = set(by_trade.keys())

        all_present = (present == expected) and not duplicate
        all_settled = all(
            str(by_trade[n].status or "").upper() == "SETTLED"
            and by_trade[n].profit is not None
            for n in expected
            if n in by_trade
        ) if all_present else False

        if not (all_present and all_settled):
            return {
                "authoritative": False,
                "cycle_pnl": None,
                "cycle_stake": sum(
                    float(r.stake or 0)
                    for r in rows
                ),
                "cycle_trades": len(rows),
            }

        cycle_pnl = sum(
            float(by_trade[n].profit or 0)
            for n in range(1, target_trade_no + 1)
        )
        cycle_stake = sum(
            float(by_trade[n].stake or 0)
            for n in range(1, target_trade_no + 1)
        )

        return {
            "authoritative": True,
            "cycle_pnl": float(cycle_pnl),
            "cycle_stake": float(cycle_stake),
            "cycle_trades": target_trade_no,
        }


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

        key = (
            sid,
            str(contract_id),
        )

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

                # Subscription/fallback responses may repeat the sold state.
                # Account settlement P/L exactly once, but still clean any
                # lingering process-local owner for this already-settled
                # contract. Otherwise a new cycle can be stranded in
                # FAST_DECISION_APPLYING forever.
                if (
                    log
                    and str(log.status).upper() == "SETTLED"
                ):
                    active_fast = self.fast_contracts.get(sid)

                    # Settlement can arrive before the market-tick callback
                    # gets CPU time. Keep an UNDECIDED fast owner alive so the
                    # exact strategy tick can still register WIN/LOSS.
                    if (
                        active_fast
                        and str(active_fast.get("contract_id") or "")
                        == str(contract_id)
                        and bool(active_fast.get("decided"))
                    ):
                        self.fast_contracts.pop(sid, None)

                    self.retired_fast_contracts.pop(
                        (int(sid), str(contract_id)),
                        None,
                    )

                    if (
                        str(s.open_contract_id or "")
                        == str(contract_id)
                    ):
                        s.open_contract_id = None

                    execution_state = self.execution_contract_state.get(int(sid))
                    if (
                        isinstance(execution_state, dict)
                        and str(execution_state.get("contract_id") or "")
                        == str(contract_id)
                        and log.profit is not None
                    ):
                        official = "WIN" if float(log.profit) > 0 else "LOSS"
                        execution_state["official_result"] = official
                        if execution_state.get("decision_mode") == "OFFICIAL_ONLY_INFLIGHT_TICK":
                            execution_state["decided"] = True
                            execution_state["decision_source"] = "DERIV_SETTLEMENT"
                        self.execution_contract_state[int(sid)] = execution_state
                        snapshot = self.digit_score_snapshots.get(int(sid))
                        if isinstance(snapshot, dict):
                            snapshot["execution_contract"] = json.loads(
                                json.dumps(execution_state)
                            )

                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                profit = float(
                    poc.get("profit") or 0
                )

                if log:
                    log.status = "SETTLED"
                    log.profit = profit
                    log.settled_at = datetime.utcnow()

                    try:
                        existing_raw = json.loads(log.raw_json or "{}")
                        if not isinstance(existing_raw, dict):
                            existing_raw = {"previous_raw": existing_raw}
                    except Exception:
                        existing_raw = {"previous_raw_text": log.raw_json}

                    existing_raw["deriv_settlement"] = data
                    existing_raw["settlement_profit"] = float(profit)
                    existing_raw["settlement_result"] = (
                        "WIN" if profit > 0 else "LOSS"
                    )
                    log.raw_json = json.dumps(existing_raw)

                s.pnl = float(s.pnl or 0) + profit

                account = (
                    db.query(DerivAccount)
                    .filter(
                        DerivAccount.user_id == user_id,
                        DerivAccount.account_id == account_id,
                    )
                    .first()
                )

                if (
                    account
                    and account.balance is not None
                ):
                    account.balance = (
                        float(account.balance)
                        + profit
                    )
                    account.updated_at = datetime.utcnow()

                # Never clear a newer open contract while an older one settles.
                if (
                    str(s.open_contract_id or "")
                    == str(contract_id)
                ):
                    s.open_contract_id = None

                # Official settlement does NOT advance the strategy.
                # It only verifies the already-made fast decision.
                fast = self.fast_contracts.get(sid)
                if not (
                    fast
                    and str(fast.get("contract_id"))
                    == str(contract_id)
                ):
                    fast = self.retired_fast_contracts.get(
                        (int(sid), str(contract_id))
                    )

                official = (
                    "WIN"
                    if profit > 0
                    else "LOSS"
                )

                execution_state = self.execution_contract_state.get(int(sid))
                if (
                    isinstance(execution_state, dict)
                    and str(execution_state.get("contract_id") or "")
                    == str(contract_id)
                ):
                    execution_state["official_result"] = official
                    if execution_state.get("decision_mode") == "OFFICIAL_ONLY_INFLIGHT_TICK":
                        execution_state["decided"] = True
                        execution_state["decision_source"] = "DERIV_SETTLEMENT"
                        execution_state["local_result"] = None
                    self.execution_contract_state[int(sid)] = execution_state
                    snapshot = self.digit_score_snapshots.get(int(sid))
                    if isinstance(snapshot, dict):
                        snapshot["execution_contract"] = json.loads(
                            json.dumps(execution_state)
                        )

                if fast:
                    fast["official_result"] = official

                    # Expose the exact authoritative settlement used for
                    # notifications. Telegram must never infer winning profit
                    # from the pre-settlement session P/L.
                    cycle_summary = self._authoritative_cycle_summary(
                        db,
                        log,
                    )

                    self.last_settlement_by_sid[sid] = {
                        "contract_id": str(contract_id),
                        "trade_no": int(log.trade_no) if log else None,
                        "digit": int(log.digit) if log else int(fast.get("target_digit")),
                        "stake": float(log.stake) if log and log.stake is not None else None,
                        "buy_price": float(log.buy_price) if log and log.buy_price is not None else None,
                        "payout": float(log.payout) if log and log.payout is not None else None,
                        "profit": float(profit),
                        "result": official,
                        "settled_at": datetime.utcnow().isoformat(),

                        # Exact cycle accounting from persisted Deriv settlements.
                        "cycle_pnl_authoritative": bool(
                            cycle_summary.get("authoritative")
                        ),
                        "cycle_pnl": cycle_summary.get("cycle_pnl"),
                        "cycle_total_stake": cycle_summary.get("cycle_stake"),
                        "cycle_trade_count": cycle_summary.get("cycle_trades"),
                    }

                    if (
                        fast.get("fast_result")
                        and fast["fast_result"]
                        != official
                    ):
                        s.running = False
                        s.paused = False
                        s.phase = "RECONCILE_MISMATCH"
                        s.last_error = (
                            "Fast tick result "
                            f"{fast['fast_result']} disagreed with "
                            f"Deriv settlement {official} for "
                            f"contract {contract_id}"
                        )

                # If FAST_WON has already occurred, an older losing contract
                # may settle after the winning contract. Refresh the pending WIN
                # summary so Telegram can publish once the entire cycle is fully
                # reconciled, without replacing it with this older LOSS.
                pending_win = self.last_settlement_by_sid.get(sid)
                if (
                    pending_win
                    and str(pending_win.get("result") or "").upper() == "WIN"
                    and not bool(pending_win.get("cycle_pnl_authoritative"))
                ):
                    winning_contract_id = str(
                        pending_win.get("contract_id") or ""
                    )
                    winning_log = (
                        db.query(TradeLog)
                        .filter(
                            TradeLog.trading_session_id == sid,
                            TradeLog.contract_id == winning_contract_id,
                        )
                        .order_by(TradeLog.id.desc())
                        .first()
                    )
                    if winning_log:
                        refreshed = self._authoritative_cycle_summary(
                            db,
                            winning_log,
                        )
                        pending_win["cycle_pnl_authoritative"] = bool(
                            refreshed.get("authoritative")
                        )
                        pending_win["cycle_pnl"] = refreshed.get("cycle_pnl")
                        pending_win["cycle_total_stake"] = refreshed.get("cycle_stake")
                        pending_win["cycle_trade_count"] = refreshed.get("cycle_trades")
                        self.last_settlement_by_sid[sid] = pending_win

                s.updated_at = datetime.utcnow()
                db.commit()

                # Official settlement is now recorded. Do NOT remove a
                # matching active fast owner until its local next-tick decision
                # has actually been made. Settlement and tick callbacks are
                # asynchronous; settlement can otherwise win the scheduling
                # race and suppress a genuine digit match.
                active_fast = self.fast_contracts.get(sid)
                if (
                    active_fast
                    and str(active_fast.get("contract_id") or "")
                    == str(contract_id)
                    and bool(active_fast.get("decided"))
                ):
                    self.fast_contracts.pop(sid, None)

                self.retired_fast_contracts.pop(
                    (int(sid), str(contract_id)),
                    None,
                )

            finally:
                db.close()

        sub_id = self.contract_subscriptions.pop(
            key,
            None,
        )

        client = self.clients.get(
            (user_id, account_id)
        )

        if client and sub_id:
            asyncio.create_task(
                self._forget_quietly(
                    client,
                    sub_id,
                )
            )

        poll = self.contract_poll_tasks.pop(
            key,
            None,
        )

        if (
            poll
            and poll is not asyncio.current_task()
            and not poll.done()
        ):
            poll.cancel()

    def last_settlement_status(self, sid: int):
        """Return the latest authoritative Deriv settlement for this session."""
        value = self.last_settlement_by_sid.get(int(sid))
        return dict(value) if isinstance(value, dict) else None

engine = MultiUserEngine()