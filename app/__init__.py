"""
DigitMatchStar canonical rank-stream fix V3.

Goals:
1. UI/API polling must NEVER recalculate or overwrite the authoritative rank.
2. The server keeps a canonical tick/rank feed alive even while trading is idle.
3. After a Render restart, ranking history is rebuilt from Deriv's latest
   historical ticks before the live subscription continues.
4. Trading mathematics and DEMO execution behavior are not changed.
"""

import asyncio
from collections import deque

from .engine import MultiUserEngine
from .db import SessionLocal
from .models import TradingSession
from .deriv_ws import DerivWS


if not hasattr(DerivWS, "ticks_history"):

    async def _ticks_history(self, symbol: str, count: int = 100):
        return await self.request(
            {
                "ticks_history": str(symbol),
                "count": max(10, min(int(count), 5000)),
                "end": "latest",
                "style": "ticks",
            }
        )

    DerivWS.ticks_history = _ticks_history


if not getattr(MultiUserEngine, "_dms_rank_snapshot_guard_v3", False):
    _original_score_all_digits = MultiUserEngine._score_all_digits

    def _score_all_digits_canonical(self, sid: int, exclude_digit=None):
        sid = int(sid)

        cached = (
            (getattr(self, "digit_score_snapshots", {}) or {})
            .get(sid)
        )

        try:
            latest_scored_epoch = int(
                (getattr(self, "_last_scored_epoch", {}) or {})
                .get(sid)
                or 0
            )
        except Exception:
            latest_scored_epoch = 0

        try:
            cached_rank_epoch = int(
                (cached or {}).get("rank_epoch")
                or 0
            )
        except Exception:
            cached_rank_epoch = 0

        if (
            exclude_digit is None
            and isinstance(cached, dict)
            and cached
            and latest_scored_epoch > 0
            and cached_rank_epoch == latest_scored_epoch
        ):
            return cached

        snapshot = _original_score_all_digits(
            self,
            sid,
            exclude_digit=exclude_digit,
        )

        latest_tick = dict(
            (getattr(self, "latest_ticks", {}) or {})
            .get(sid)
            or {}
        )

        try:
            server_epoch = int(
                latest_tick.get("epoch")
                or (getattr(self, "latest_tick_epoch", {}) or {}).get(sid)
                or 0
            )
        except Exception:
            server_epoch = 0

        try:
            rank_epoch = int(
                (getattr(self, "_last_scored_epoch", {}) or {}).get(sid)
                or 0
            )
        except Exception:
            rank_epoch = 0

        try:
            server_digit = self._tick_last_digit(latest_tick)
        except Exception:
            server_digit = None

        snapshot["canonical_tick"] = {
            "epoch": server_epoch,
            "digit": server_digit,
            "quote": latest_tick.get("quote"),
            "pip_size": latest_tick.get("pip_size"),
            "symbol": latest_tick.get("symbol"),
        }

        snapshot["rank_epoch"] = rank_epoch
        snapshot["shadow_epoch"] = rank_epoch

        shadow = snapshot.get("shadow")
        if isinstance(shadow, dict):
            shadow["rank_epoch"] = rank_epoch

        selected_digit = snapshot.get("selected_digit")
        live_next = (
            (getattr(self, "live_next_target", {}) or {})
            .get(sid)
        )

        try:
            same_target = (
                selected_digit is not None
                and live_next is not None
                and int(selected_digit) == int(live_next)
            )
        except Exception:
            same_target = False

        target_epoch = (
            rank_epoch
            if same_target and rank_epoch > 0
            else 0
        )

        snapshot["target_epoch"] = target_epoch
        snapshot["target_digit"] = (
            int(live_next)
            if live_next is not None
            else None
        )

        snapshot["sync_ready"] = bool(
            server_epoch > 0
            and rank_epoch > 0
            and target_epoch > 0
            and server_epoch == rank_epoch == target_epoch
        )

        self.digit_score_snapshots[sid] = snapshot
        return snapshot

    MultiUserEngine._score_all_digits = _score_all_digits_canonical
    MultiUserEngine._dms_rank_snapshot_guard_v3 = True


if not getattr(MultiUserEngine, "_dms_history_bootstrap_v3", False):

    async def _bootstrap_rank_history(
        self,
        sid: int,
        symbol: str,
        client,
    ):
        sid = int(sid)

        bootstrapped = getattr(
            self,
            "_dms_bootstrapped_rank_sessions",
            None,
        )
        if bootstrapped is None:
            bootstrapped = set()
            self._dms_bootstrapped_rank_sessions = bootstrapped

        if sid in bootstrapped:
            return

        existing = self._digit_history(sid)
        if len(existing) >= int(self.digit_scorer.min_history):
            bootstrapped.add(sid)
            return

        data = await client.ticks_history(
            str(symbol),
            count=int(self.digit_scorer.max_history),
        )

        hist = data.get("history") or {}
        prices = list(hist.get("prices") or [])
        times = list(hist.get("times") or [])

        pip_size = (
            data.get("pip_size")
            if data.get("pip_size") is not None
            else hist.get("pip_size")
        )

        if not prices:
            return

        rebuilt = deque(
            maxlen=int(self.digit_scorer.max_history)
        )

        for price in prices[-int(self.digit_scorer.max_history):]:
            digit = self._tick_last_digit(
                {
                    "quote": price,
                    "pip_size": pip_size,
                }
            )
            if digit is not None:
                rebuilt.append(int(digit))

        if not rebuilt:
            return

        self.digit_history[sid] = rebuilt

        last_epoch = 0
        if times:
            try:
                last_epoch = int(times[-1] or 0)
            except Exception:
                last_epoch = 0

        last_quote = prices[-1]

        self.latest_ticks[sid] = {
            "epoch": last_epoch,
            "quote": last_quote,
            "pip_size": pip_size,
            "symbol": str(symbol),
        }

        if last_epoch > 0:
            self.latest_tick_epoch[sid] = last_epoch

            if not hasattr(self, "_last_scored_epoch"):
                self._last_scored_epoch = {}

            self._last_scored_epoch[sid] = last_epoch

        snapshot = self._score_all_digits(sid)

        if snapshot.get("ready"):
            selected = snapshot.get("selected_digit")
            if selected is not None:
                self._set_live_next_target(
                    sid,
                    int(selected),
                )

                snapshot["target_digit"] = int(selected)
                snapshot["target_epoch"] = int(last_epoch or 0)
                snapshot["sync_ready"] = bool(
                    last_epoch > 0
                    and int(snapshot.get("rank_epoch") or 0)
                    == last_epoch
                )

        bootstrapped.add(sid)

    MultiUserEngine._bootstrap_rank_history = _bootstrap_rank_history
    MultiUserEngine._dms_history_bootstrap_v3 = True


if not getattr(MultiUserEngine, "_dms_passive_rank_feed_v3", False):

    async def _ensure_passive_rank_feed(
        self,
        sid: int,
        user_id: str,
        account_id: str,
        symbol: str,
    ):
        sid = int(sid)

        try:
            client = await self._client(
                str(user_id),
                str(account_id),
            )

            await self._bootstrap_rank_history(
                sid,
                str(symbol),
                client,
            )

            await self._ensure_tick_subscription(
                sid=sid,
                user_id=str(user_id),
                account_id=str(account_id),
                symbol=str(symbol),
                client=client,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        finally:
            tasks = getattr(
                self,
                "_dms_passive_feed_tasks",
                {},
            )
            current = tasks.get(sid)
            if current is asyncio.current_task():
                tasks.pop(sid, None)

    async def _passive_rank_feed_loop(self):
        if not hasattr(self, "_dms_passive_feed_tasks"):
            self._dms_passive_feed_tasks = {}

        while True:
            try:
                db = SessionLocal()
                try:
                    rows = db.query(TradingSession).all()

                    sessions = [
                        (
                            int(row.id),
                            str(row.user_id),
                            str(row.account_id),
                            str(row.symbol),
                        )
                        for row in rows
                    ]
                finally:
                    db.close()

                live_ids = {sid for sid, *_ in sessions}

                for sid, task in list(
                    self._dms_passive_feed_tasks.items()
                ):
                    if sid not in live_ids:
                        if task and not task.done():
                            task.cancel()
                        self._dms_passive_feed_tasks.pop(
                            sid,
                            None,
                        )

                for sid, user_id, account_id, symbol in sessions:
                    existing = (
                        (getattr(self, "tick_subscriptions", {}) or {})
                        .get(sid)
                    )

                    needs_setup = (
                        not existing
                        or str(existing.get("symbol"))
                        != str(symbol)
                    )

                    if not needs_setup:
                        continue

                    task = self._dms_passive_feed_tasks.get(
                        sid
                    )

                    if task and not task.done():
                        continue

                    self._dms_passive_feed_tasks[sid] = (
                        asyncio.create_task(
                            self._ensure_passive_rank_feed(
                                sid,
                                user_id,
                                account_id,
                                symbol,
                            )
                        )
                    )

            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            await asyncio.sleep(1.0)

    _original_engine_start = MultiUserEngine.start

    async def _start_with_passive_rank_feed(self):
        await _original_engine_start(self)

        task = getattr(
            self,
            "_dms_passive_rank_feed_task",
            None,
        )

        if not task or task.done():
            self._dms_passive_rank_feed_task = (
                asyncio.create_task(
                    self._passive_rank_feed_loop()
                )
            )

    MultiUserEngine._ensure_passive_rank_feed = (
        _ensure_passive_rank_feed
    )
    MultiUserEngine._passive_rank_feed_loop = (
        _passive_rank_feed_loop
    )
    MultiUserEngine.start = _start_with_passive_rank_feed
    MultiUserEngine._dms_passive_rank_feed_v3 = True
