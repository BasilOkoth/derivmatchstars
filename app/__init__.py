"""
DigitMatchStar Rank Recovery V5 + Contract Tick Timeline V4.

Key rule:
- ONLY the canonical server tick handler computes a new rank.
- API/UI reads NEVER call or wrap the scorer.
"""

import asyncio
import json
from datetime import datetime
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


# ---------------------------------------------------------------------------
# Target Eligibility Gate V6
#
# A digit may become a purchased target only when V1 rank #1 score >= 9.0.
#
# Behaviour:
# - Ranking still calculates and displays all 10 digits on every canonical tick.
# - If top score < 9.0, no proposal/buy is sent.
# - Trade 1 waits until a future canonical tick produces score >= 9.0.
# - After a loss, the stake advances once, then the recovery waits until a
#   future canonical tick produces score >= 9.0.
# - The open contract target remains immutable.
# ---------------------------------------------------------------------------

if not getattr(MultiUserEngine, "_dms_min_score_9_v6", False):

    MIN_TARGET_SCORE_V6 = 9.0

    _original_score_all_digits_v6 = MultiUserEngine._score_all_digits
    _original_handle_strategy_tick_v6 = MultiUserEngine._handle_strategy_tick
    _original_step_v6 = MultiUserEngine.step

    def _score_all_digits_min9(
        self,
        sid: int,
        exclude_digit=None,
    ):
        sid = int(sid)

        snapshot = _original_score_all_digits_v6(
            self,
            sid,
            exclude_digit=exclude_digit,
        )

        ranking = snapshot.get("ranking") or []

        raw_digit = None
        raw_score = None

        if ranking:
            try:
                raw_digit = int(ranking[0].get("digit"))
            except Exception:
                raw_digit = None

            try:
                raw_score = float(ranking[0].get("score"))
            except Exception:
                raw_score = None

        eligible = bool(
            snapshot.get("ready")
            and raw_digit is not None
            and raw_score is not None
            and raw_score >= MIN_TARGET_SCORE_V6
        )

        snapshot["raw_selected_digit"] = raw_digit
        snapshot["raw_top_score"] = raw_score
        snapshot["target_min_score"] = MIN_TARGET_SCORE_V6
        snapshot["target_eligible"] = eligible
        snapshot["target_gate"] = "V1_TOP_SCORE_GE_9"

        # selected_digit is the EXECUTION selection. Preserve the full ranking
        # even when no digit is currently eligible.
        snapshot["selected_digit"] = raw_digit if eligible else None

        if not eligible:
            # Never leave a stale "next target" visible/executable.
            self.live_next_target.pop(sid, None)

        # The original scorer stores this same snapshot, but assign explicitly
        # so readers always see the gated execution state.
        self.digit_score_snapshots[sid] = snapshot

        return snapshot

    async def _step_min9(self, sid: int):
        sid = int(sid)

        # Prevent the normal step loop from repeatedly trying Trade 1 while
        # the rank is valid but below the score threshold.
        db = SessionLocal()
        try:
            s = db.get(TradingSession, sid)

            if (
                s
                and s.running
                and not s.paused
                and int(s.current_trade or 0) == 0
                and not s.open_contract_id
            ):
                snapshot = (
                    (getattr(self, "digit_score_snapshots", {}) or {})
                    .get(sid)
                    or {}
                )

                if (
                    snapshot.get("ready")
                    and snapshot.get("target_eligible") is False
                ):
                    changed = (
                        str(s.phase or "") != "WAITING_SCORE_GE_9"
                        or s.candidate_digit is not None
                        or s.last_error is not None
                    )

                    if changed:
                        s.candidate_digit = None
                        s.phase = "WAITING_SCORE_GE_9"
                        s.last_error = None
                        s.updated_at = datetime.utcnow()
                        db.commit()

                    return

            waiting = (
                (getattr(self, "_dms_score9_waiting", {}) or {})
                .get(sid)
            )

            # Recovery waiting is driven only by canonical ticks in
            # _handle_strategy_tick_min9(). Do not let step() bypass the gate.
            if s and waiting and s.running and not s.paused:
                return

        finally:
            db.close()

        return await _original_step_v6(self, sid)

    async def _buy_waiting_score9(
        self,
        *,
        sid: int,
        user_id: str,
        account_id: str,
        symbol: str,
    ):
        sid = int(sid)

        waiting_map = getattr(self, "_dms_score9_waiting", {})
        waiting = waiting_map.get(sid)

        if not waiting:
            return False

        snapshot = (
            (getattr(self, "digit_score_snapshots", {}) or {})
            .get(sid)
            or {}
        )

        if not snapshot.get("target_eligible"):
            return False

        digit = snapshot.get("selected_digit")
        if digit is None:
            return False

        digit = int(digit)

        async with self._lock(sid):
            # Re-check after acquiring the session lock.
            waiting = waiting_map.get(sid)
            if not waiting:
                return False

            snapshot = (
                (getattr(self, "digit_score_snapshots", {}) or {})
                .get(sid)
                or {}
            )

            if not snapshot.get("target_eligible"):
                return False

            digit = snapshot.get("selected_digit")
            if digit is None:
                return False

            digit = int(digit)

            db = SessionLocal()

            try:
                s = db.get(TradingSession, sid)

                if (
                    not s
                    or not s.running
                    or s.paused
                    or int(s.current_trade or 0) >= int(s.max_trades or 0)
                ):
                    waiting_map.pop(sid, None)
                    return False

                expected_trade_no = int(s.current_trade or 0) + 1

                if expected_trade_no != int(
                    waiting.get("trade_no") or expected_trade_no
                ):
                    waiting_map.pop(sid, None)
                    return False

                # The stake was advanced exactly once when the previous fast
                # loss entered WAITING_SCORE_GE_9.
                s.candidate_digit = digit
                self._set_live_next_target(sid, digit)

                self.locked_target_snapshots[sid] = {
                    "digit": digit,
                    "snapshot": json.loads(json.dumps(snapshot)),
                    "locked_at": datetime.utcnow().isoformat(),
                }

                s.phase = "SCORE_GE_9_ELIGIBLE"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()

                currency = await self._currency_for(db, s)
                client = await self._client(user_id, account_id)

                payload = await self._request_proposal_payload(
                    client,
                    symbol=s.symbol,
                    digit=digit,
                    stake=s.current_stake,
                    trade_no=expected_trade_no,
                    currency=currency,
                )

                ok = await self._execute_buy(
                    db,
                    s,
                    client,
                    payload,
                    prearmed=True,
                )

                if ok:
                    waiting_map.pop(sid, None)

                return bool(ok)

            finally:
                db.close()

    async def _handle_strategy_tick_min9(
        self,
        *,
        sid,
        user_id,
        account_id,
        symbol,
        data,
    ):
        sid = int(sid)

        active_before = (
            (getattr(self, "fast_contracts", {}) or {})
            .get(sid)
        )

        active_contract_before = (
            str(active_before.get("contract_id") or "")
            if isinstance(active_before, dict)
            else ""
        )

        active_was_undecided = bool(
            isinstance(active_before, dict)
            and not active_before.get("decided")
        )

        await _original_handle_strategy_tick_v6(
            self,
            sid=sid,
            user_id=user_id,
            account_id=account_id,
            symbol=symbol,
            data=data,
        )

        snapshot = (
            (getattr(self, "digit_score_snapshots", {}) or {})
            .get(sid)
            or {}
        )

        if not hasattr(self, "_dms_score9_waiting"):
            self._dms_score9_waiting = {}

        waiting_map = self._dms_score9_waiting

        # If a current contract just fast-lost on a tick whose new top score is
        # below 9, the underlying engine intentionally receives
        # selected_digit=None. It therefore enters RERANK_NOT_READY. Convert
        # that technical state into our deliberate "wait for >= 9" state.
        active_after = (
            (getattr(self, "fast_contracts", {}) or {})
            .get(sid)
        )

        just_lost = bool(
            active_was_undecided
            and isinstance(active_after, dict)
            and str(active_after.get("contract_id") or "")
                == active_contract_before
            and str(active_after.get("fast_result") or "").upper()
                == "LOSS"
        )

        if (
            just_lost
            and snapshot.get("ready")
            and snapshot.get("target_eligible") is False
        ):
            db = SessionLocal()

            try:
                s = db.get(TradingSession, sid)

                if s and int(s.current_trade or 0) < int(s.max_trades or 0):
                    # Advance martingale stake ONCE for the next trade.
                    # The original engine calculates this value but does not
                    # assign it when selected_digit is None.
                    next_stake = round(
                        float(s.current_stake)
                        * float(s.multiplier),
                        2,
                    )

                    s.current_stake = next_stake
                    s.candidate_digit = None
                    s.running = True
                    s.paused = False
                    s.phase = "WAITING_SCORE_GE_9"
                    s.last_error = None
                    s.updated_at = datetime.utcnow()
                    db.commit()

                    self.live_next_target.pop(sid, None)
                    self.locked_target_snapshots.pop(sid, None)

                    waiting_map[sid] = {
                        "trade_no": int(s.current_trade or 0) + 1,
                        "stake": next_stake,
                        "entered_after_contract": active_contract_before,
                        "minimum_score": MIN_TARGET_SCORE_V6,
                    }

            finally:
                db.close()

            return

        # While waiting after a loss, every new canonical tick is ranked.
        # The FIRST tick whose top V1 score reaches >= 9 becomes the next
        # executable target.
        if sid in waiting_map:
            if snapshot.get("target_eligible"):
                await self._buy_waiting_score9(
                    sid=sid,
                    user_id=user_id,
                    account_id=account_id,
                    symbol=symbol,
                )

    MultiUserEngine._score_all_digits = _score_all_digits_min9
    MultiUserEngine.step = _step_min9
    MultiUserEngine._buy_waiting_score9 = _buy_waiting_score9
    MultiUserEngine._handle_strategy_tick = _handle_strategy_tick_min9
    MultiUserEngine._dms_min_score_9_v6 = True


# ---------------------------------------------------------------------------
# InvalidContractProposal Recovery V7
#
# Deriv can explicitly reject a proposal id with:
#   InvalidContractProposal: Unknown contract proposal
#
# That response means the BUY was NOT created, so this is not a genuinely
# uncertain purchase. Safely clear the abandoned BUY_CLAIM, request one fresh
# proposal on the current socket, and retry exactly once (DEMO only).
# ---------------------------------------------------------------------------

if not getattr(MultiUserEngine, "_dms_invalid_proposal_retry_v7", False):

    _original_execute_buy_v7 = MultiUserEngine._execute_buy

    async def _execute_buy_retry_invalid_proposal(
        self,
        db,
        s,
        client,
        payload,
        *,
        prearmed: bool,
    ):
        try:
            return await _original_execute_buy_v7(
                self,
                db,
                s,
                client,
                payload,
                prearmed=prearmed,
            )

        except RuntimeError as exc:
            text = str(exc)
            lower = text.lower()

            explicit_invalid = (
                "invalidcontractproposal" in lower
                or "unknown contract proposal" in lower
            )

            retry_count = int(
                payload.get("_invalid_proposal_retry_count", 0)
                or 0
            )

            # Only retry an explicit proposal rejection, once, and only for
            # DEMO. REAL automated BUY remains disabled in deriv_ws.py.
            if (
                not explicit_invalid
                or retry_count >= 1
                or str(getattr(s, "account_mode", "")).upper() != "DEMO"
            ):
                raise

            sid = int(s.id)

            row = (
                db.query(TradingSession)
                .filter(TradingSession.id == sid)
                .with_for_update()
                .one_or_none()
            )

            if not row:
                raise

            # Core _execute_buy marks every BUY exception as BUY_UNCERTAIN.
            # This specific Deriv error is different: it explicitly rejected
            # the proposal id, so no contract was created.
            row.pending_trade_json = None
            row.running = True
            row.paused = False
            row.phase = "REFRESHING_INVALID_PROPOSAL"
            row.last_error = None
            row.updated_at = datetime.utcnow()
            db.commit()

            # Ensure we are using the current account socket, then request a
            # completely fresh proposal for the same digit/stake/trade.
            fresh_client = await self._client(
                row.user_id,
                row.account_id,
            )

            fresh_payload = await self._request_proposal_payload(
                fresh_client,
                symbol=row.symbol,
                digit=int(payload["digit"]),
                stake=float(payload["stake"]),
                trade_no=int(payload["trade_no"]),
                currency=str(payload.get("currency") or "USD"),
            )

            fresh_payload["_invalid_proposal_retry_count"] = 1
            fresh_payload["replaces_proposal_id"] = payload.get(
                "proposal_id"
            )

            row = db.get(TradingSession, sid)
            if row:
                row.phase = "RETRYING_FRESH_PROPOSAL"
                row.updated_at = datetime.utcnow()
                db.commit()

            return await _original_execute_buy_v7(
                self,
                db,
                row,
                fresh_client,
                fresh_payload,
                prearmed=prearmed,
            )

    MultiUserEngine._execute_buy = (
        _execute_buy_retry_invalid_proposal
    )
    MultiUserEngine._dms_invalid_proposal_retry_v7 = True


# ---------------------------------------------------------------------------
# Score>=9 Initial-Trade None Guard V8
#
# Fixes:
#   PROPOSAL [.../digit None]: int() argument must be ... NoneType
#
# Root cause:
# The score>=9 gate can intentionally make selected_digit=None while the
# engine's original Trade-1 step is still allowed to continue into the normal
# proposal path. V8 takes full ownership of Trade 1 whenever current_trade=0:
# it either waits, or explicitly freezes an eligible digit before requesting
# a proposal. A None digit can never reach _request_proposal_payload().
# ---------------------------------------------------------------------------

if not getattr(MultiUserEngine, "_dms_score9_none_guard_v8", False):

    _previous_step_v8 = MultiUserEngine.step
    _previous_request_proposal_v8 = MultiUserEngine._request_proposal_payload

    async def _request_proposal_payload_no_none_v8(
        self,
        client,
        *,
        symbol,
        digit,
        stake,
        trade_no,
        currency,
    ):
        if digit is None:
            raise RuntimeError(
                "SCORE_GATE_WAIT: no eligible target digit yet"
            )

        return await _previous_request_proposal_v8(
            self,
            client,
            symbol=symbol,
            digit=int(digit),
            stake=stake,
            trade_no=trade_no,
            currency=currency,
        )

    async def _step_score9_trade1_v8(self, sid: int):
        sid = int(sid)

        db = SessionLocal()

        try:
            s = db.get(TradingSession, sid)

            if not s or not s.running or s.paused:
                return

            # Only take over the untouched first trade. Once a contract has
            # actually been purchased, existing core/V6 recovery logic resumes.
            if (
                int(s.current_trade or 0) != 0
                or s.open_contract_id
            ):
                return await _previous_step_v8(self, sid)

            # Make sure the canonical server tick stream exists.
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

            snapshot = (
                (getattr(self, "digit_score_snapshots", {}) or {})
                .get(sid)
                or {}
            )

            # No valid score yet: wait.
            if not snapshot.get("ready"):
                s.candidate_digit = None
                s.phase = "DIGIT_SCORE_WARMING"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()
                return

            # V6 sets target_eligible and selected_digit only when top score>=9.
            eligible = bool(snapshot.get("target_eligible"))
            digit = snapshot.get("selected_digit")

            if not eligible or digit is None:
                s.candidate_digit = None
                s.phase = "WAITING_SCORE_GE_9"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()

                self.live_next_target.pop(sid, None)
                self.locked_target_snapshots.pop(sid, None)
                return

            digit = int(digit)

            # Re-check that the selected row itself satisfies the threshold.
            selected_row = None
            for row in snapshot.get("ranking") or []:
                try:
                    if int(row.get("digit")) == digit:
                        selected_row = row
                        break
                except Exception:
                    continue

            try:
                selected_score = float(
                    (selected_row or {}).get("score")
                )
            except Exception:
                selected_score = None

            minimum_score = float(
                snapshot.get("target_min_score") or 9.0
            )

            if (
                selected_score is None
                or selected_score < minimum_score
            ):
                s.candidate_digit = None
                s.phase = "WAITING_SCORE_GE_9"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()

                self.live_next_target.pop(sid, None)
                self.locked_target_snapshots.pop(sid, None)
                return

            # Freeze exactly the snapshot that qualified.
            s.candidate_digit = digit
            self._set_live_next_target(sid, digit)

            self.locked_target_snapshots[sid] = {
                "digit": digit,
                "snapshot": json.loads(json.dumps(snapshot)),
                "locked_at": datetime.utcnow().isoformat(),
            }

            s.phase = "SCORE_GE_9_ELIGIBLE"
            s.last_error = None
            s.updated_at = datetime.utcnow()
            db.commit()

            currency = await self._currency_for(db, s)

            # Final DB re-read immediately before proposal so stale/None
            # candidate state cannot leak into the request.
            s = db.get(TradingSession, sid)

            if (
                not s
                or not s.running
                or s.paused
                or s.candidate_digit is None
            ):
                return

            proposal_digit = int(s.candidate_digit)

            payload = await self._request_proposal_payload(
                client,
                symbol=s.symbol,
                digit=proposal_digit,
                stake=s.current_stake,
                trade_no=1,
                currency=currency,
            )

            # If a new canonical tick changed the live ranking while the
            # proposal was being requested, the purchased target remains the
            # already-frozen eligible Trade-1 target.
            return await self._execute_buy(
                db,
                s,
                client,
                payload,
                prearmed=False,
            )

        finally:
            db.close()

    MultiUserEngine._request_proposal_payload = (
        _request_proposal_payload_no_none_v8
    )
    MultiUserEngine.step = _step_score9_trade1_v8
    MultiUserEngine._dms_score9_none_guard_v8 = True
