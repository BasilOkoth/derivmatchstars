"""
DigitMatchStar Rank Recovery V5 + Contract Tick Timeline V4.

Key rule:
- ONLY the canonical server tick handler computes a new rank.
- API/UI reads NEVER call or wrap the scorer.
"""

import asyncio
from collections import deque
from time import monotonic

from .engine import MultiUserEngine
from .db import SessionLocal
from .models import TradingSession
from .deriv_ws import DerivWS


if not hasattr(DerivWS, "ticks_history"):
    async def _ticks_history(self, symbol: str, count: int = 100):
        return await self.request({
            "ticks_history": str(symbol),
            "count": max(10, min(int(count), 5000)),
            "end": "latest",
            "style": "ticks",
        })
    DerivWS.ticks_history = _ticks_history


if not getattr(MultiUserEngine, "_dms_rank_feed_v5", False):

    _original_handle_tick_v5 = MultiUserEngine._handle_strategy_tick
    _original_start_v5 = MultiUserEngine.start

    async def _handle_tick_rank_health(
        self,
        *,
        sid,
        user_id,
        account_id,
        symbol,
        data,
    ):
        if not hasattr(self, "_dms_last_tick_monotonic"):
            self._dms_last_tick_monotonic = {}

        self._dms_last_tick_monotonic[int(sid)] = monotonic()

        return await _original_handle_tick_v5(
            self,
            sid=int(sid),
            user_id=user_id,
            account_id=account_id,
            symbol=symbol,
            data=data,
        )

    async def _bootstrap_rank_history(
        self,
        sid: int,
        symbol: str,
        client,
    ):
        sid = int(sid)

        if len(self._digit_history(sid)) >= int(self.digit_scorer.min_history):
            return

        data = await client.ticks_history(
            str(symbol),
            count=int(self.digit_scorer.max_history),
        )

        hist = data.get("history") or {}
        prices = list(hist.get("prices") or [])
        times = list(hist.get("times") or [])

        if not prices:
            return

        pip_size = (
            data.get("pip_size")
            if data.get("pip_size") is not None
            else hist.get("pip_size")
        )

        rebuilt = deque(maxlen=int(self.digit_scorer.max_history))

        for price in prices[-int(self.digit_scorer.max_history):]:
            d = self._tick_last_digit({
                "quote": price,
                "pip_size": pip_size,
            })
            if d is not None:
                rebuilt.append(int(d))

        if not rebuilt:
            return

        self.digit_history[sid] = rebuilt

        last_epoch = 0
        if times:
            try:
                last_epoch = int(times[-1] or 0)
            except Exception:
                last_epoch = 0

        self.latest_ticks[sid] = {
            "epoch": last_epoch,
            "quote": prices[-1],
            "pip_size": pip_size,
            "symbol": str(symbol),
        }

        if last_epoch:
            self.latest_tick_epoch[sid] = last_epoch
            if not hasattr(self, "_last_scored_epoch"):
                self._last_scored_epoch = {}
            self._last_scored_epoch[sid] = last_epoch

        # This is the only non-live score calculation: one bootstrap snapshot
        # immediately after historical reconstruction.
        snapshot = self._score_all_digits(sid)
        snapshot["rank_epoch"] = last_epoch or None
        snapshot["canonical_tick"] = {
            "epoch": last_epoch or None,
            "digit": self._tick_last_digit(self.latest_ticks[sid]),
            "quote": prices[-1],
            "pip_size": pip_size,
            "symbol": str(symbol),
        }

        if snapshot.get("ready"):
            selected = snapshot.get("selected_digit")
            if selected is not None:
                self._set_live_next_target(sid, int(selected))

    async def _ensure_feed(
        self,
        sid: int,
        user_id: str,
        account_id: str,
        symbol: str,
        *,
        force=False,
    ):
        sid = int(sid)
        try:
            client = await self._client(user_id, account_id)
            await self._bootstrap_rank_history(sid, symbol, client)

            existing = self.tick_subscriptions.get(sid)
            if force and existing:
                sub_id = existing.get("subscription_id")
                self.tick_subscriptions.pop(sid, None)
                if sub_id:
                    try:
                        await client.forget(sub_id)
                    except Exception:
                        pass

            await self._ensure_tick_subscription(
                sid=sid,
                user_id=user_id,
                account_id=account_id,
                symbol=symbol,
                client=client,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _rank_feed_watchdog(self):
        if not hasattr(self, "_dms_last_tick_monotonic"):
            self._dms_last_tick_monotonic = {}

        while True:
            try:
                db = SessionLocal()
                try:
                    rows = db.query(TradingSession).all()
                    sessions = [
                        (
                            int(r.id),
                            str(r.user_id),
                            str(r.account_id),
                            str(r.symbol),
                        )
                        for r in rows
                    ]
                finally:
                    db.close()

                now = monotonic()

                for sid, user_id, account_id, symbol in sessions:
                    existing = self.tick_subscriptions.get(sid)
                    last_seen = self._dms_last_tick_monotonic.get(sid)

                    stale = (
                        existing is not None
                        and last_seen is not None
                        and (now - last_seen) > 12.0
                    )

                    missing = (
                        not existing
                        or str(existing.get("symbol")) != str(symbol)
                    )

                    if missing or stale:
                        asyncio.create_task(
                            self._ensure_feed(
                                sid,
                                user_id,
                                account_id,
                                symbol,
                                force=bool(stale),
                            )
                        )

            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            await asyncio.sleep(2.0)

    async def _start_rank_feed_v5(self):
        await _original_start_v5(self)

        task = getattr(self, "_dms_rank_watchdog_task", None)
        if not task or task.done():
            self._dms_rank_watchdog_task = asyncio.create_task(
                self._rank_feed_watchdog()
            )

    MultiUserEngine._handle_strategy_tick = _handle_tick_rank_health
    MultiUserEngine._bootstrap_rank_history = _bootstrap_rank_history
    MultiUserEngine._ensure_rank_feed = _ensure_feed
    MultiUserEngine._rank_feed_watchdog = _rank_feed_watchdog
    MultiUserEngine.start = _start_rank_feed_v5
    MultiUserEngine._dms_rank_feed_v5 = True


# Contract timeline diagnostics. Display/telemetry only.
if not getattr(MultiUserEngine, "_dms_trade_timeline_v4", False):

    _original_execute_buy_v4 = MultiUserEngine._execute_buy
    _original_handle_strategy_tick_v4 = MultiUserEngine._handle_strategy_tick
    _original_last_settlement_status_v4 = MultiUserEngine.last_settlement_status

    async def _execute_buy_with_timeline(
        self, db, s, client, payload, *, prearmed: bool
    ):
        sid = int(s.id)
        snap = (
            (getattr(self, "locked_target_snapshots", {}) or {})
            .get(sid, {})
            .get("snapshot")
            or (getattr(self, "digit_score_snapshots", {}) or {}).get(sid)
            or {}
        )
        canonical = snap.get("canonical_tick") or {}

        origin_epoch = int(
            snap.get("rank_epoch")
            or canonical.get("epoch")
            or 0
        )
        origin_digit = canonical.get("digit")

        ok = await _original_execute_buy_v4(
            self, db, s, client, payload, prearmed=prearmed
        )
        if not ok:
            return ok

        active = (getattr(self, "fast_contracts", {}) or {}).get(sid)
        if not isinstance(active, dict):
            return ok

        if not hasattr(self, "trade_timeline_by_sid"):
            self.trade_timeline_by_sid = {}

        self.trade_timeline_by_sid[sid] = {
            "contract_id": str(active.get("contract_id") or ""),
            "trade_no": int(active.get("trade_no") or 0),
            "symbol": str(active.get("symbol") or ""),
            "prediction_origin_epoch": origin_epoch or None,
            "prediction_origin_digit": (
                int(origin_digit) if origin_digit is not None else None
            ),
            "target_digit": int(active.get("target_digit")),
            "armed_after_epoch": int(
                active.get("armed_after_epoch") or 0
            ) or None,
            "result_epoch": None,
            "result_digit": None,
            "fast_result": "WAITING",
            "comparison": None,
        }

        return ok

    async def _handle_tick_with_timeline(
        self, *, sid, user_id, account_id, symbol, data
    ):
        sid = int(sid)
        tick = data.get("tick") or {}
        epoch = int(tick.get("epoch") or 0)
        active = (getattr(self, "fast_contracts", {}) or {}).get(sid)

        if (
            isinstance(active, dict)
            and str(active.get("symbol")) == str(symbol)
            and not active.get("decided")
        ):
            armed = int(active.get("armed_after_epoch") or 0)

            if not epoch or not armed or epoch > armed:
                result_digit = self._tick_last_digit(tick)

                if result_digit is not None:
                    target = int(active.get("target_digit"))

                    if not hasattr(self, "trade_timeline_by_sid"):
                        self.trade_timeline_by_sid = {}

                    current = dict(
                        self.trade_timeline_by_sid.get(sid) or {}
                    )
                    current.update({
                        "contract_id": str(active.get("contract_id") or ""),
                        "trade_no": int(active.get("trade_no") or 0),
                        "symbol": str(symbol),
                        "target_digit": target,
                        "armed_after_epoch": armed or None,
                        "result_epoch": epoch or None,
                        "result_digit": int(result_digit),
                        "fast_result": (
                            "WIN" if int(result_digit) == target else "LOSS"
                        ),
                        "comparison": (
                            f"{target} = {int(result_digit)}"
                            if int(result_digit) == target
                            else f"{target} != {int(result_digit)}"
                        ),
                    })
                    self.trade_timeline_by_sid[sid] = current

        return await _original_handle_strategy_tick_v4(
            self,
            sid=sid,
            user_id=user_id,
            account_id=account_id,
            symbol=symbol,
            data=data,
        )

    def _last_settlement_with_timeline(self, sid: int):
        base = _original_last_settlement_status_v4(self, int(sid))
        timeline = (
            (getattr(self, "trade_timeline_by_sid", {}) or {})
            .get(int(sid))
        )

        if not timeline:
            return base

        payload = dict(base) if isinstance(base, dict) else {}
        payload["trade_timeline"] = dict(timeline)

        same = (
            str(payload.get("contract_id") or "")
            == str(timeline.get("contract_id") or "")
            and bool(payload.get("contract_id"))
        )

        payload["trade_timeline"]["official_contract_match"] = same

        if same:
            payload["trade_timeline"]["official_result"] = payload.get("result")
            payload["trade_timeline"]["official_profit"] = payload.get("profit")

        return payload

    MultiUserEngine._execute_buy = _execute_buy_with_timeline
    MultiUserEngine._handle_strategy_tick = _handle_tick_with_timeline
    MultiUserEngine.last_settlement_status = _last_settlement_with_timeline
    MultiUserEngine._dms_trade_timeline_v4 = True
