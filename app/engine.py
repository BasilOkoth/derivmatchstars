import asyncio
import json
import uuid
import time
import logging
from datetime import datetime
from collections import deque
import math

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
      3. Market ticks update predictions and provisional diagnostics.
      4. Deriv official contract settlement determines WIN or LOSS.
      5. Verified losses alone authorize the next purchase.
      6. Three-trade blocks use the database purchase-log digit.

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
        self.contract_subscription_tasks = {}  # setup task per contract
        self.contract_poll_tasks = {}  # fallback only

        # Latest live V1 rank #1 for the NEXT trade.
        # This may change while a purchased contract is open; the purchased
        # contract itself remains immutable at Deriv.
        self.live_next_target = {}  # sid -> digit

        # AI FUSION V1: latest browser Digit Intelligence recommendation.
        # The browser can suggest, but only this server may authorize a BUY.
        self.ai_signal_by_sid = {}  # sid -> validated AI evidence

        # Forward-only prediction scoreboard. Each prepared V1/AI signal is
        # evaluated exactly once against the next canonical SERVER tick.
        self.prediction_performance_by_sid = {}  # sid -> aggregate counters
        self.prediction_performance_last_seq = {}  # sid -> last evaluated prepared rank_seq

        # GREEN AI forward recorder. Browser AI arrives asynchronously from a
        # separate Deriv websocket, so it cannot rely on already-built V1 snapshots.
        # Keep a short canonical server tick ledger and bind every green AI call
        # to its source tick, then score it exactly once against source_seq + 1.
        self.canonical_tick_history_by_sid = {}  # sid -> deque of canonical server ticks
        self.green_ai_pending_by_sid = {}        # sid -> latest unscored green AI forecast
        self.green_ai_scored_sources_by_sid = {}  # sid -> deque of scored source keys

        # Unified 0-9 scoring + target recycling.
        self.digit_scorer = DigitScoreEngine(recycle_after=3, min_history=10, max_history=100)

        # V1 MARGIN GATE
        # Rank #1 is executable only when its lead over rank #2 reaches the
        # user-configured minimum. Shared by DEMO and REAL target selection.
        self.minimum_v1_margin_default = 3.0
        self.minimum_v1_margin_by_sid = {}
        self.digit_history = {}          # sid -> deque(maxlen=200)
        self.digit_score_snapshots = {}  # sid -> latest ranking
        self.shadow_200_snapshots = {}  # sid -> research-only 200-tick challenger
        self.shadow_200_scorer = DigitScoreEngine(recycle_after=3, min_history=10, max_history=200)
        # Process memory is lost on Render restart. Rebuild DigitScore from
        # Deriv's recent ticks_history before the next cycle starts.
        self.history_bootstrap_tasks = {}   # sid -> asyncio.Task
        self.history_bootstrap_generation = {}  # sid -> client connection generation
        # Exact final observation already included by ticks_history. Deriv may
        # replay this same observation as the first live subscription callback.
        self.history_bootstrap_last_tick = {}  # sid -> bootstrap boundary evidence
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
                and snapshot.get("selected_digit") is not None
                and (value <= 0 or (margin_value is not None and margin_value >= value))
            )
            snapshot["minimum_v1_margin"] = value
            snapshot["margin_eligible"] = eligible
            snapshot["margin_status"] = (
                "READY" if eligible
                else "WAITING_MARGIN" if snapshot.get("ready")
                else "WARMING"
            )

        return value

    @staticmethod
    def _ai_number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number

    def _canonical_tick_ledger(self, sid: int):
        sid = int(sid)
        ledger = self.canonical_tick_history_by_sid.get(sid)
        if ledger is None:
            ledger = deque(maxlen=12)
            self.canonical_tick_history_by_sid[sid] = ledger
        return ledger

    @staticmethod
    def _green_ai_source_key(signal: dict):
        if not isinstance(signal, dict):
            return None
        return (
            int(signal.get("source_tick_epoch") or 0),
            str(signal.get("source_tick_quote") or ""),
            int(signal.get("source_tick_digit"))
            if signal.get("source_tick_digit") is not None else None,
        )

    @staticmethod
    def _tick_identity_key(tick: dict):
        if not isinstance(tick, dict):
            return None
        return (
            int(tick.get("epoch") or 0),
            str(tick.get("formatted_quote") or ""),
            int(tick.get("digit")) if tick.get("digit") is not None else None,
        )

    def _green_ai_scored_sources(self, sid: int):
        sid = int(sid)
        rows = self.green_ai_scored_sources_by_sid.get(sid)
        if rows is None:
            rows = deque(maxlen=1000)
            self.green_ai_scored_sources_by_sid[sid] = rows
        return rows

    def _record_green_ai_result(self, sid: int, forecast: dict, observed_tick: dict):
        """Count one green AI T+1 forecast exactly once."""
        sid = int(sid)
        source_key = self._green_ai_source_key(forecast)
        if source_key is None:
            return False
        scored = self._green_ai_scored_sources(sid)
        if source_key in scored:
            return False

        try:
            predicted = int(forecast.get("digit"))
            observed = int(observed_tick.get("digit"))
            source_seq = int(forecast.get("source_seq") or 0)
            observed_seq = int(observed_tick.get("seq") or 0)
        except (TypeError, ValueError):
            return False

        # Strict forward-only rule: only the immediately following canonical tick.
        if source_seq <= 0 or observed_seq != source_seq + 1:
            return False

        matched = predicted == observed
        state = self._prediction_performance_state(sid)
        state["green_ai_total"] += 1
        state["green_ai_matches"] += int(matched)
        state["last_green_ai_outcome"] = {
            "source_seq": source_seq,
            "source_epoch": forecast.get("source_tick_epoch"),
            "source_quote": forecast.get("source_tick_quote"),
            "predicted_digit": predicted,
            "score": float(forecast.get("score") or 0.0),
            "observed_seq": observed_seq,
            "observed_epoch": observed_tick.get("epoch"),
            "observed_digit": observed,
            "matched": bool(matched),
        }
        scored.append(source_key)
        self.green_ai_pending_by_sid.pop(sid, None)
        return True

    def _arm_or_score_green_ai(self, sid: int, signal: dict):
        """Bind a green browser AI call to canonical server tick T.

        If T+1 is already in the short ledger (browser POST arrived late), score it
        immediately. Otherwise keep the forecast armed until the next server tick.
        """
        sid = int(sid)
        if not isinstance(signal, dict) or float(signal.get("score") or 0.0) < 0.85:
            return False
        source_key = self._green_ai_source_key(signal)
        if not source_key or source_key[0] <= 0 or not source_key[1] or source_key[2] is None:
            return False
        if source_key in self._green_ai_scored_sources(sid):
            return True

        ledger = list(self._canonical_tick_ledger(sid))
        source_tick = next((t for t in ledger if self._tick_identity_key(t) == source_key), None)
        pending = dict(signal)
        pending["armed"] = False
        pending["source_seq"] = None

        if source_tick is not None:
            source_seq = int(source_tick.get("seq") or 0)
            pending["source_seq"] = source_seq or None
            pending["armed"] = bool(source_seq)
            if source_seq:
                next_tick = next((t for t in ledger if int(t.get("seq") or 0) == source_seq + 1), None)
                if next_tick is not None:
                    return self._record_green_ai_result(sid, pending, next_tick)

        self.green_ai_pending_by_sid[sid] = pending
        return bool(pending.get("armed"))

    def _advance_green_ai_forward_recorder(self, sid: int, current_tick: dict):
        """Advance/score the pending green AI forecast on canonical server ticks."""
        sid = int(sid)
        if not isinstance(current_tick, dict):
            return
        pending = self.green_ai_pending_by_sid.get(sid)
        if not isinstance(pending, dict):
            return

        current_seq = int(current_tick.get("seq") or 0)
        if current_seq <= 0:
            return

        source_key = self._green_ai_source_key(pending)
        current_key = self._tick_identity_key(current_tick)

        # Signal may arrive before the server sees its source tick. Bind it here.
        if not pending.get("source_seq"):
            if source_key == current_key:
                pending["source_seq"] = current_seq
                pending["armed"] = True
                self.green_ai_pending_by_sid[sid] = pending
            return

        source_seq = int(pending.get("source_seq") or 0)
        if current_seq == source_seq + 1:
            self._record_green_ai_result(sid, pending, current_tick)
        elif current_seq > source_seq + 1:
            # We missed T+1; never substitute a later tick. Keep diagnostics honest.
            state = self._prediction_performance_state(sid)
            state["last_green_ai_drop"] = {
                "reason": "MISSED_EXACT_NEXT_TICK",
                "source_seq": source_seq,
                "current_seq": current_seq,
            }
            self.green_ai_pending_by_sid.pop(sid, None)

    def _bind_ai_signal_to_canonical_server_tick(self, sid: int, signal: dict):
        """Map a browser AI T+1 forecast onto the server's canonical sequence.

        Browser and server subscribe through different websocket connections, so
        comparing their *latest* epochs directly is incorrect.  We instead find
        the browser source observation in the short canonical server ledger and
        bind the forecast to that server sequence number.  Only a forecast bound
        to the SAME sequence as the prepared V1 snapshot may influence a BUY.
        """
        sid = int(sid)
        if not isinstance(signal, dict):
            return signal

        source_key = self._green_ai_source_key(signal)
        ledger = list(self._canonical_tick_ledger(sid))
        match = None
        if source_key and source_key[0] > 0 and source_key[1] and source_key[2] is not None:
            match = next((t for t in ledger if self._tick_identity_key(t) == source_key), None)

        latest_seq = int(ledger[-1].get("seq") or 0) if ledger else 0
        if match is None:
            signal["bound_source_seq"] = None
            signal["binding_status"] = "WAITING_SERVER_SOURCE_TICK"
            signal["server_latest_seq_at_bind"] = latest_seq or None
            return signal

        source_seq = int(match.get("seq") or 0)
        signal["bound_source_seq"] = source_seq or None
        signal["bound_server_tick"] = dict(match)
        signal["server_latest_seq_at_bind"] = latest_seq or None

        if source_seq and latest_seq == source_seq:
            signal["binding_status"] = "CANONICAL_BOUND"
        elif source_seq and latest_seq > source_seq:
            signal["binding_status"] = "LATE_FOR_EXECUTION"
        else:
            signal["binding_status"] = "WAITING_SERVER_SOURCE_TICK"
        return signal

    def _bind_waiting_ai_on_server_tick(self, sid: int, canonical_tick: dict):
        """Promote a waiting browser AI signal when its exact source tick reaches server."""
        sid = int(sid)
        signal = self.ai_signal_by_sid.get(sid)
        if not isinstance(signal, dict) or not isinstance(canonical_tick, dict):
            return False
        if str(signal.get("binding_status") or "") != "WAITING_SERVER_SOURCE_TICK":
            return False
        if self._green_ai_source_key(signal) != self._tick_identity_key(canonical_tick):
            return False

        seq = int(canonical_tick.get("seq") or 0)
        if seq <= 0:
            return False
        signal["bound_source_seq"] = seq
        signal["bound_server_tick"] = dict(canonical_tick)
        signal["server_latest_seq_at_bind"] = seq
        signal["binding_status"] = "CANONICAL_BOUND"
        self.ai_signal_by_sid[sid] = signal
        return True

    def set_ai_signal(self, sid: int, *, symbol: str, payload: dict):
        sid = int(sid)
        digit = int(payload.get("digit"))
        score = self._ai_number(payload.get("score"))
        if digit < 0 or digit > 9:
            raise ValueError("AI digit must be 0..9")
        if score is None or score < 0 or score > 1:
            raise ValueError("AI score must be between 0 and 1")

        clean = {
            "digit": digit,
            "score": score,
            "source": str(payload.get("source") or "AI")[:120],
            "symbol": str(symbol),
            "pm5": self._ai_number(payload.get("pm5")),
            "pm10": self._ai_number(payload.get("pm10")),
            "s20": self._ai_number(payload.get("s20")),
            "etm": self._ai_number(payload.get("etm")),
            "dna": self._ai_number(payload.get("dna")),
            "features": self._ai_number(payload.get("features")),
            "auditor": self._ai_number(payload.get("auditor")),
            "source_tick_epoch": payload.get("source_tick_epoch"),
            "source_tick_quote": (
                str(payload.get("source_tick_quote"))
                if payload.get("source_tick_quote") is not None
                else None
            ),
            "source_tick_digit": (
                int(payload.get("source_tick_digit"))
                if payload.get("source_tick_digit") is not None
                else None
            ),
            "client_ts_ms": payload.get("client_ts_ms"),
            "received_monotonic": time.monotonic(),
            "received_at": datetime.utcnow().isoformat(),
        }
        clean = self._bind_ai_signal_to_canonical_server_tick(sid, clean)
        self.ai_signal_by_sid[sid] = clean

        # If this forecast maps to the CURRENT prepared server sequence, refresh
        # that snapshot's fusion immediately.  This avoids waiting for another
        # market tick just to make the newly-arrived AI signal visible/executable.
        current_snapshot = self.digit_score_snapshots.get(sid)
        if (
            isinstance(current_snapshot, dict)
            and int(clean.get("bound_source_seq") or 0) > 0
            and int(current_snapshot.get("rank_seq") or 0) == int(clean.get("bound_source_seq") or 0)
            and str(clean.get("binding_status") or "") == "CANONICAL_BOUND"
        ):
            canonical = current_snapshot.get("canonical_tick") or {}
            self._fusion_select(sid, current_snapshot, symbol=canonical.get("symbol"))

        # Green AI is a forward T+1 forecast. Arm it independently of the V1
        # snapshot so asynchronous browser/server timing cannot make hits vanish.
        if float(score) >= 0.85:
            self._arm_or_score_green_ai(sid, clean)

        return {k: v for k, v in clean.items() if k != "received_monotonic"}

    def _fresh_ai_signal(self, sid: int, *, symbol=None, max_age_seconds=3.0):
        signal = self.ai_signal_by_sid.get(int(sid))
        if not isinstance(signal, dict):
            return None
        if symbol is not None and str(signal.get("symbol")) != str(symbol):
            return None
        received = float(signal.get("received_monotonic") or 0.0)
        age = time.monotonic() - received if received else 999999.0
        if age < 0 or age > float(max_age_seconds):
            return None
        out = dict(signal)
        out["age_seconds"] = float(age)
        return out

    def ai_signal_status(self, sid: int, *, symbol=None):
        signal = self._fresh_ai_signal(int(sid), symbol=symbol)
        if not signal:
            raw = self.ai_signal_by_sid.get(int(sid))
            if not isinstance(raw, dict):
                return {"ready": False, "status": "MISSING"}
            out = dict(raw)
            out["ready"] = False
            out["status"] = "STALE_OR_SYMBOL_MISMATCH"
            out.pop("received_monotonic", None)
            return out
        signal["ready"] = True
        signal["status"] = "FRESH"
        signal.pop("received_monotonic", None)
        return signal

    def _fusion_select(self, sid: int, snapshot: dict, *, symbol=None):
        v1_digit = snapshot.get("selected_digit")
        v1_ready = bool(snapshot.get("ready") and v1_digit is not None)
        v1_margin_ok = bool(snapshot.get("margin_eligible"))

        # V3 canonical-sequence alignment. Browser/server websocket clocks are
        # not compared directly. The browser AI source observation is first
        # mapped onto the server's canonical tick ledger; only the forecast
        # bound to this snapshot's rank_seq can influence execution.
        ai_raw = self._fresh_ai_signal(int(sid), symbol=symbol)
        canonical = snapshot.get("canonical_tick") or {}
        expected_seq = int(snapshot.get("rank_seq") or 0)
        expected_epoch = canonical.get("epoch")
        expected_quote = canonical.get("formatted_quote")
        expected_digit = canonical.get("digit")

        tick_match = False
        tick_mismatch_reason = None
        ai = None

        if ai_raw:
            bound_seq = int(ai_raw.get("bound_source_seq") or 0)
            binding_status = str(ai_raw.get("binding_status") or "UNBOUND")
            if binding_status == "CANONICAL_BOUND" and bound_seq and expected_seq and bound_seq == expected_seq:
                tick_match = True
                ai = ai_raw
            elif binding_status == "WAITING_SERVER_SOURCE_TICK":
                tick_mismatch_reason = "WAITING_SERVER_SOURCE_TICK"
            elif binding_status == "LATE_FOR_EXECUTION":
                tick_mismatch_reason = "AI_LATE_FOR_EXECUTION"
            elif bound_seq and expected_seq and bound_seq != expected_seq:
                tick_mismatch_reason = "SERVER_SEQ_MISMATCH"
            else:
                tick_mismatch_reason = "AI_NOT_CANONICAL_BOUND"

        ai_digit = int(ai["digit"]) if ai else None
        ai_score = float(ai["score"]) if ai else None

        support = 0
        support_flags = {}
        if ai:
            checks = {
                "dna": (ai.get("dna"), 0.55),
                "features": (ai.get("features"), 0.60),
                "auditor": (ai.get("auditor"), 0.55),
                "pm5": (ai.get("pm5"), 0.40),
                "pm10": (ai.get("pm10"), 0.60),
            }
            for name, (value, threshold) in checks.items():
                ok = value is not None and float(value) >= float(threshold)
                support_flags[name] = bool(ok)
                support += int(ok)

        agreement = bool(
            ai and tick_match and v1_ready
            and int(ai_digit) == int(v1_digit)
            and ai_score is not None and ai_score >= 0.55
        )
        green_ai_primary = bool(
            ai and tick_match and ai_score is not None and ai_score >= 0.85
        )
        ai_override = bool(
            ai and tick_match and ai_score is not None and ai_score >= 0.62 and support >= 3
        )

        final_digit = None
        source = "NO_EXECUTABLE_SIGNAL"
        if agreement:
            final_digit = int(v1_digit)
            source = "AI_V1_AGREEMENT"
        elif green_ai_primary:
            final_digit = int(ai_digit)
            source = "GREEN_AI_PRIMARY"
        elif ai_override:
            final_digit = int(ai_digit)
            source = "AI_OVERRIDE"
        elif v1_ready and v1_margin_ok:
            final_digit = int(v1_digit)
            if ai_raw and not tick_match:
                source = "V1_AI_CANONICAL_WAIT"
            else:
                source = "V1"
        elif ai_raw and not tick_match:
            source = "WAITING_AI_CANONICAL_BIND"
        elif ai_raw is None:
            source = "V1_AI_STALE"
        else:
            source = "WAITING_FUSION_STRENGTH"

        result = {
            "version": "AI_V1_FUSION_V3_CANONICAL_SEQ",
            "executable": final_digit is not None,
            "final_digit": final_digit,
            "source": source,
            "tick_aligned": bool(tick_match),
            "alignment_mode": "SERVER_CANONICAL_SEQUENCE",
            "tick_mismatch_reason": tick_mismatch_reason,
            "expected_tick": {
                "epoch": expected_epoch,
                "formatted_quote": expected_quote,
                "digit": expected_digit,
                "rank_seq": snapshot.get("rank_seq"),
            },
            "v1_digit": int(v1_digit) if v1_digit is not None else None,
            "v1_margin_eligible": v1_margin_ok,
            "v1_top_margin": snapshot.get("top_margin"),
            "ai_digit": ai_digit,
            "ai_score": ai_score,
            "ai_bound_source_seq": (int(ai_raw.get("bound_source_seq") or 0) or None) if ai_raw else None,
            "ai_binding_status": ai_raw.get("binding_status") if ai_raw else None,
            "green_ai": bool(green_ai_primary),
            "green_ai_threshold": 0.85,
            "ai_support_count": int(support),
            "ai_support_flags": support_flags,
            "ai": ({k: v for k, v in ai.items() if k != "received_monotonic"} if ai else None),
            "rejected_ai": ({k: v for k, v in ai_raw.items() if k != "received_monotonic"} if ai_raw and not tick_match else None),
        }
        snapshot["fusion"] = result
        return result

    def _prediction_performance_state(self, sid: int):
        sid = int(sid)
        state = self.prediction_performance_by_sid.get(sid)
        if not isinstance(state, dict):
            state = {
                "green_ai_total": 0,
                "green_ai_matches": 0,
                "v1_total": 0,
                "v1_matches": 0,
                "fusion_total": 0,
                "fusion_matches": 0,
                "last_outcome": None,
                "last_green_ai_outcome": None,
                "last_green_ai_drop": None,
            }
            self.prediction_performance_by_sid[sid] = state
        return state

    def prediction_performance_status(self, sid: int):
        state = dict(self._prediction_performance_state(int(sid)))

        def rate(matches, total):
            return (float(matches) / float(total)) if total else None

        state["green_ai_rate"] = rate(
            state.get("green_ai_matches", 0),
            state.get("green_ai_total", 0),
        )
        state["v1_rate"] = rate(
            state.get("v1_matches", 0),
            state.get("v1_total", 0),
        )
        state["fusion_rate"] = rate(
            state.get("fusion_matches", 0),
            state.get("fusion_total", 0),
        )
        state["green_ai_threshold"] = 0.85
        pending = self.green_ai_pending_by_sid.get(int(sid))
        state["green_ai_pending"] = (
            {k: v for k, v in pending.items() if k != "received_monotonic"}
            if isinstance(pending, dict) else None
        )
        return state

    def _score_previous_prediction(self, sid: int, previous_snapshot: dict, *, observed_digit, current_seq):
        """Score one prepared snapshot against the next canonical server tick.

        This is forward-only: snapshot rank_seq N is evaluated when sequence N+1
        arrives. Duplicate rescoring/API refreshes cannot increase the counters.
        """
        if not isinstance(previous_snapshot, dict):
            return
        try:
            prepared_seq = int(previous_snapshot.get("rank_seq") or 0)
            current_seq = int(current_seq or 0)
            observed_digit = int(observed_digit)
        except (TypeError, ValueError):
            return
        if prepared_seq <= 0 or current_seq <= prepared_seq:
            return
        if int(self.prediction_performance_last_seq.get(int(sid), 0) or 0) >= prepared_seq:
            return

        state = self._prediction_performance_state(int(sid))
        fusion = previous_snapshot.get("fusion") or {}

        v1_digit = fusion.get("v1_digit", previous_snapshot.get("selected_digit"))
        ai_digit = fusion.get("ai_digit")
        ai_score = fusion.get("ai_score")
        final_digit = fusion.get("final_digit")
        tick_aligned = bool(fusion.get("tick_aligned"))

        v1_match = None
        ai_match = None
        fusion_match = None

        if v1_digit is not None:
            try:
                v1_digit = int(v1_digit)
                state["v1_total"] += 1
                v1_match = (v1_digit == observed_digit)
                state["v1_matches"] += int(v1_match)
            except (TypeError, ValueError):
                pass

        # GREEN AI is scored by the independent forward recorder armed by
        # set_ai_signal(). Browser AI arrives asynchronously and must not depend
        # on whether it happened to be present inside this V1 snapshot.
        green_ai = False

        if final_digit is not None and bool(fusion.get("executable")):
            try:
                final_digit = int(final_digit)
                state["fusion_total"] += 1
                fusion_match = (final_digit == observed_digit)
                state["fusion_matches"] += int(fusion_match)
            except (TypeError, ValueError):
                pass

        state["last_outcome"] = {
            "prepared_rank_seq": prepared_seq,
            "observed_seq": current_seq,
            "observed_digit": observed_digit,
            "v1_digit": v1_digit,
            "v1_match": v1_match,
            "green_ai_digit": int(ai_digit) if green_ai else None,
            "green_ai_score": float(ai_score) if green_ai else None,
            "green_ai_match": ai_match,
            "fusion_digit": final_digit,
            "fusion_match": fusion_match,
            "fusion_source": fusion.get("source"),
        }
        self.prediction_performance_last_seq[int(sid)] = prepared_seq

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

            await asyncio.sleep(0.10)

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
            history = deque(maxlen=200)
            self.digit_history[sid] = history
        return history

    def _score_all_digits(self, sid: int, exclude_digit=None):
        previous_snapshot = self.digit_score_snapshots.get(int(sid))
        snapshot = self.digit_scorer.rank(
            list(self._digit_history(sid))[-100:],
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

        # Maintain a short exact canonical tick ledger for asynchronous browser
        # AI forecasts. Dedupe API-triggered re-scores of the same market tick.
        canonical_now = snapshot.get("canonical_tick") or {}
        if canonical_now.get("seq"):
            ledger = self._canonical_tick_ledger(int(sid))
            seq_now = int(canonical_now.get("seq") or 0)
            if not ledger or int(ledger[-1].get("seq") or 0) != seq_now:
                ledger.append(dict(canonical_now))
            self._bind_waiting_ai_on_server_tick(int(sid), canonical_now)
            self._advance_green_ai_forward_recorder(int(sid), canonical_now)

        # Score the PREVIOUS prepared forecast against this newly-arrived
        # canonical tick before publishing the new prediction.
        current_tick = snapshot.get("canonical_tick") or {}
        current_digit = current_tick.get("digit")
        current_seq = snapshot.get("rank_seq")
        if current_digit is not None and current_seq:
            self._score_previous_prediction(
                int(sid),
                previous_snapshot,
                observed_digit=current_digit,
                current_seq=current_seq,
            )
        snapshot["prediction_performance"] = self.prediction_performance_status(int(sid))

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
            and snapshot.get("selected_digit") is not None
            and (minimum_margin <= 0 or (
                margin_value is not None and margin_value >= minimum_margin
            ))
        )

        snapshot["minimum_v1_margin"] = minimum_margin
        snapshot["margin_eligible"] = margin_eligible
        snapshot["margin_status"] = (
            "READY" if margin_eligible
            else "WAITING_MARGIN" if snapshot.get("ready")
            else "WARMING"
        )

        # 200-tick challenger is shadow research only: NEVER alters purchased digit.
        history_200 = list(self._digit_history(sid))
        shadow_200 = self.shadow_200_scorer.rank(history_200)
        self.shadow_200_snapshots[sid] = {
            "version": "DIGIT_SCORE_200_SHADOW",
            "history_count": len(history_200),
            "selected_digit": shadow_200.get("selected_digit"),
            "top_margin": shadow_200.get("top_margin"),
            "rank_seq": snapshot.get("rank_seq"),
        }
        snapshot["shadow_200"] = dict(self.shadow_200_snapshots[sid])

        latest_symbol = None
        if isinstance(snapshot.get("canonical_tick"), dict):
            latest_symbol = snapshot["canonical_tick"].get("symbol")
        self._fusion_select(sid, snapshot, symbol=latest_symbol)

        self.digit_score_snapshots[sid] = snapshot
        return snapshot

    # DMS_THREE_TRADE_TRANSACTIONAL_LOCK_V15
    def _three_trade_locked_target(self, s, *, db=None):
        """Read the actual block-anchor PURCHASE from the SAME database transaction.

        The previous V14 implementation opened another database session even inside
        SELECT ... FOR UPDATE, permitting inconsistent snapshots and lock contention.
        No in-memory V1/candidate digit can supersede an anchor purchase.
        """
        n = int(s.current_trade or 0)
        if n <= 0 or n % 3 == 0:
            return None
        anchor_trade_no = ((n - 1) // 3) * 3 + 1
        own_db = db is None
        session = db if db is not None else SessionLocal()
        try:
            recent = (session.query(TradeLog)
                      .filter(TradeLog.trading_session_id == int(s.id))
                      .order_by(TradeLog.id.desc()).limit(n).all())
            recent.reverse()
            numbers = [int(row.trade_no or 0) for row in recent]
            if len(recent) != n or numbers != list(range(1, n + 1)):
                raise RuntimeError(
                    f"THREE_TRADE_INVALID_CYCLE sid={s.id} current={n} trades={numbers}"
                )
            anchor = recent[anchor_trade_no - 1]
            if not anchor.contract_id or anchor.digit is None:
                raise RuntimeError(
                    f"THREE_TRADE_MISSING_ANCHOR sid={s.id} trade={anchor_trade_no}"
                )
            target = int(anchor.digit)
            if target not in range(10):
                raise RuntimeError(f"THREE_TRADE_BAD_ANCHOR_DIGIT sid={s.id}")
            # Verify EVERY purchased trade in the current block agrees.
            for previous in recent[anchor_trade_no - 1:]:
                if not previous.contract_id or int(previous.digit) != target:
                    raise RuntimeError(
                        f"THREE_TRADE_BLOCK_MISMATCH sid={s.id} "
                        f"trade={previous.trade_no} anchor={target} purchased={previous.digit}"
                    )
            return target
        finally:
            if own_db:
                session.close()

    def _choose_scored_digit(self, sid: int, exclude_digit=None, *, lock_target=False, prepared_snapshot=None):
        snapshot = (
            self._score_all_digits(sid, exclude_digit=exclude_digit)
            if exclude_digit is not None
            else (prepared_snapshot if prepared_snapshot is not None
                  else self.digit_score_snapshots.get(sid) or {})
        )

        symbol = None
        canonical = snapshot.get("canonical_tick")
        if isinstance(canonical, dict):
            symbol = canonical.get("symbol")

        fusion = self._fusion_select(sid, snapshot, symbol=symbol)
        digit = fusion.get("final_digit")

        if digit is None:
            return None, snapshot

        if lock_target:
            self.locked_target_snapshots[sid] = {
                "digit": int(digit),
                "snapshot": json.loads(json.dumps(snapshot)),
                "locked_at": datetime.utcnow().isoformat(),
                "selector_source": fusion.get("source"),
            }

        return int(digit), snapshot

    def _trade_score_evidence(self, sid: int, digit: int):
        """Return the exact execution snapshot frozen when this block target was chosen."""
        locked = self.locked_target_snapshots.get(sid) or {}
        snapshot = locked.get("snapshot")

        if (
            not snapshot
            or int(locked.get("digit", -1)) != int(digit)
        ):
            snapshot = self.digit_score_snapshots.get(sid) or {}

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
            "selector_source": locked.get("selector_source"),
            "fusion": snapshot.get("fusion"),
            "ai_signal": (
                snapshot.get("fusion", {}).get("ai")
                if isinstance(snapshot.get("fusion"), dict)
                else None
            ),
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
        count=200,
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
                    count=max(200, int(count or 200)),
                )

                payload = result.get("history") or {}
                prices = list(payload.get("prices") or [])
                times = list(payload.get("times") or [])
                pip_size = result.get("pip_size")

                if not prices:
                    return False

                # Replace an incomplete process-local window with the canonical
                # recent history returned by Deriv, preserving chronological order.
                rebuilt = deque(maxlen=200)

                usable_times = len(times) == len(prices)
                last_epoch = 0

                for idx, price in enumerate(prices[-200:]):
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
                            epoch = int(times[-len(prices[-200:]) + idx])
                            last_epoch = max(last_epoch, epoch)
                        except Exception:
                            pass

                if not rebuilt:
                    return False

                self.digit_history[sid] = rebuilt

                # Record the last observation already included by ticks_history.
                # The first live subscription callback can repeat this exact
                # market observation, which must not enter DigitScore twice.
                last_bootstrap_tick = {"quote": prices[-1]}
                if pip_size is not None:
                    last_bootstrap_tick["pip_size"] = pip_size
                self.history_bootstrap_last_tick[sid] = {
                    "epoch": (
                        int(times[-1])
                        if usable_times and times
                        else int(last_epoch or 0)
                    ),
                    "formatted_quote": self._canonical_tick_text(
                        last_bootstrap_tick
                    ),
                    "digit": self._tick_last_digit(last_bootstrap_tick),
                    "generation": int(generation),
                }

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
                count=200,
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

        # De-duplicate the ticks_history -> live-subscription boundary. Match
        # BOTH epoch and canonical formatted quote, so a genuinely different
        # tick within the same second is never suppressed.
        skip_bootstrap_duplicate = False
        boundary = self.history_bootstrap_last_tick.get(int(sid))
        if tick and not is_replay and isinstance(boundary, dict):
            live_text = self._canonical_tick_text(
                tick,
                fallback_decimals=self.tick_precision.get(int(sid)),
            )
            boundary_epoch = int(boundary.get("epoch") or 0)
            boundary_text = boundary.get("formatted_quote")
            same_epoch = bool(
                epoch and boundary_epoch and int(epoch) == boundary_epoch
            )
            same_quote = bool(
                live_text is not None
                and boundary_text is not None
                and str(live_text) == str(boundary_text)
            )

            if same_epoch and same_quote:
                skip_bootstrap_duplicate = True
                self.history_bootstrap_last_tick.pop(int(sid), None)
                if not hasattr(self, "_last_scored_seq"):
                    self._last_scored_seq = {}
                if tick_seq:
                    self._last_scored_seq[int(sid)] = max(
                        int(self._last_scored_seq.get(int(sid), 0)),
                        int(tick_seq),
                    )
            elif epoch and boundary_epoch and int(epoch) > boundary_epoch:
                # The feed has moved beyond the bootstrap boundary.
                self.history_bootstrap_last_tick.pop(int(sid), None)

        # Only a new market callback may replace latest_ticks.
        if tick and not is_replay:
            cached = dict(tick)
            cached["_dms_seq"] = int(tick_seq)
            self.latest_ticks[sid] = cached

        if epoch:
            previous_epoch = int(self.latest_tick_epoch.get(sid) or 0)
            self.latest_tick_epoch[sid] = max(previous_epoch, epoch)

        # Freeze the fully prepared rank BEFORE incorporating this incoming tick.
        # A recovery triggered by this tick must use that previous-tick rank,
        # rather than a new rank derived from the trigger tick itself.
        prepared_for_this_tick = self.digit_score_snapshots.get(sid)
        if isinstance(prepared_for_this_tick, dict):
            prepared_for_this_tick = dict(prepared_for_this_tick)
        else:
            prepared_for_this_tick = {}

        digit = self._tick_last_digit(
            tick, fallback_decimals=self.tick_precision.get(int(sid))
        )
        if digit is not None:
            history = self._digit_history(sid)

            if not hasattr(self, "_last_scored_seq"):
                self._last_scored_seq = {}

            last_scored_seq = int(self._last_scored_seq.get(sid, 0))

            # Score each real market sequence exactly once.
            if (
                not is_replay
                and not skip_bootstrap_duplicate
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

                # V17: market tick is diagnostic; official Deriv settlement
                # alone controls next purchase and recovery.
                s.phase = "WAITING_OFFICIAL_SETTLEMENT"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()
                return

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

                setup = self.contract_subscription_tasks.pop(key, None)
                if setup and setup is not asyncio.current_task() and not setup.done():
                    setup.cancel()

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

                # V17: authoritative settlement owns the entire execution lifecycle.
                # Fast ticks provide diagnostics only; they NEVER advance recovery.
                # The unsettled-contract branch below remains the single waiting gate.
                if fast_owner and contract_id and str(fast_owner.get("contract_id") or "") == contract_id:
                    if latest and str(latest.status or "").upper() == "SETTLED":
                        self.fast_contracts.pop(sid, None)
                        fast_owner = None

                # No live in-memory owner means restart/recovery state.
                # We cannot safely recreate a missed "first tick after BUY"
                # across a process restart because callback sequence continuity
                # is gone. Instead, switch to fast authoritative reconciliation:
                # ask Deriv for the sold state on a sub-second/backoff cadence,
                # then resume immediately from the persisted settlement.
                if contract_id and (not latest or str(latest.status).upper() != "SETTLED"):
                    # One settlement watcher per contract. Prefer the
                    # subscription path; if Deriv returns no subscription id,
                    # _subscribe_open_contract starts its own bounded poller.
                    # Only use the urgent direct probe when no watcher is
                    # currently active. This prevents duplicate settlement
                    # requests from competing on the same account WebSocket.
                    self._schedule_contract_subscription(
                        sid=sid,
                        user_id=s.user_id,
                        account_id=s.account_id,
                        contract_id=contract_id,
                        client=client,
                    )

                    contract_key = (int(sid), str(contract_id))
                    setup_task = self.contract_subscription_tasks.get(
                        contract_key
                    )
                    poll_task = self.contract_poll_tasks.get(contract_key)
                    watcher_active = bool(
                        contract_key in self.contract_subscriptions
                        or (setup_task and not setup_task.done())
                        or (poll_task and not poll_task.done())
                    )

                    if not watcher_active:
                        self._schedule_contract_probe(
                            sid=sid,
                            user_id=s.user_id,
                            account_id=s.account_id,
                            contract_id=contract_id,
                            client=client,
                            urgent=True,
                        )
                    probe_key = (int(sid), str(contract_id))
                    probe_count = int(
                        self.contract_probe_unsold.get(probe_key, 0)
                    )
                    error_count = int(
                        self.contract_probe_errors.get(probe_key, 0)
                    )
                    # Do not rewrite an unchanged phase to PostgreSQL on
                    # every worker pass. The next purchase remains blocked by
                    # the unresolved contract and the persisted BUY claim.
                    if probe_count or error_count:
                        wait_phase = (
                            "WAITING_OFFICIAL_SETTLEMENT"
                            f"_P{probe_count}_E{error_count}"
                        )
                    else:
                        wait_phase = "WAITING_OFFICIAL_SETTLEMENT"
                    if s.phase != wait_phase:
                        s.phase = wait_phase
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
                    # A public-feed tick may differ from the settled expiry tick.
                    # The Deriv contract profit is authoritative for progression.
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
                    fresh_digit = self._three_trade_locked_target(s, db=db)
                    snapshot = {}
                    if fresh_digit is None:
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
                scored_digit = self._three_trade_locked_target(s, db=db)
                snapshot = {}
                if scored_digit is None:
                    scored_digit, snapshot = self._choose_scored_digit(
                        s.id, lock_target=True,
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

        # V17: never mutate another worker's in-flight purchase claim.
        pending_before_gate = self._pending_json(row.pending_trade_json)
        if (trade_no != expected_trade_no or row.open_contract_id
                or pending_before_gate.get("kind") == "BUY_CLAIM"):
            db.rollback()
            return None

        # AI FUSION V1 — final authoritative pre-BUY barrier.
        # New blocks use frozen eligible V1/fusion. Continuing a 3-trade
        # block uses the actual previously purchased barrier from TradeLog.
        locked = self.locked_target_snapshots.get(int(sid)) or {}
        gate_snapshot = locked.get("snapshot") or {}
        fusion = (
            gate_snapshot.get("fusion")
            if isinstance(gate_snapshot, dict)
            else None
        ) or {}

        gate_top = fusion.get("final_digit")
        gate_ok = bool(
            fusion.get("executable")
            and gate_top is not None
            and int(gate_top) == int(digit)
            and int(locked.get("digit", -1)) == int(digit)
        )

        # V13: authorize the actual purchased block-start TradeLog digit,
        # independent of mutable candidate_digit and changing V1 rankings.
        expected_locked = self._three_trade_locked_target(row, db=db)
        if expected_locked is not None:
            # Hard override: a valid live V1/fusion candidate must NEVER
            # authorize a different digit inside a 3-trade purchased block.
            if int(digit) != int(expected_locked):
                db.rollback()
                logger.error(
                    "DMS_LOCK_V15 REJECT sid=%s trade=%s proposed=%s locked=%s",
                    sid, trade_no, digit, expected_locked,
                )
                return None
            gate_ok = True
            gate_top = int(expected_locked)
            fusion = {"source": "THREE_TRADE_TRANSACTIONAL_LOCK_V15"}

        if not gate_ok:
            # Do not clear a purchase claim when selection evidence changes.
            row.running = True
            row.paused = False
            row.phase = (
                "RECOVERY_WAITING_MARGIN"
                if int(row.current_trade or 0) > 0
                else "WAITING_V1_MARGIN"
            )
            row.last_error = "Fusion target changed or is no longer executable"
            row.updated_at = datetime.utcnow()
            db.commit()
            return None

        payload["three_trade_lock"] = {
            "block_start_trade": ((trade_no - 1) // 3) * 3 + 1,
            "block_position": ((trade_no - 1) % 3) + 1,
            "purchased_target": int(digit),
            "locked_from_trade_log": expected_locked is not None,
        }

        # Freeze the exact gate evidence used to authorize this BUY.
        payload["margin_gate"] = {
            "selected_digit": int(gate_top),
            "eligible": True,
            "selector_source": fusion.get("source"),
            "v1_top_margin": gate_snapshot.get("top_margin"),
            "minimum_v1_margin": gate_snapshot.get("minimum_v1_margin"),
            "ai_score": fusion.get("ai_score"),
            "ai_support_count": fusion.get("ai_support_count"),
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

        # DMS_RACE_GUARD_V11: shared DEMO/REAL authoritative BUY boundary.
        # Never send a fresh purchase while the previous contract is open or
        # before its official settled LOSS is committed to the DB.
        pending = self._pending_json(row.pending_trade_json)
        if row.open_contract_id or pending.get("kind") == "BUY_CLAIM":
            db.rollback()
            return None
        if int(row.current_trade or 0) > 0:
            previous = (
                db.query(TradeLog)
                .filter(TradeLog.trading_session_id == int(sid))
                .order_by(TradeLog.id.desc())
                .first()
            )
            if (
                previous is None
                or int(previous.trade_no or 0) != int(row.current_trade or 0)
                or str(previous.status or "").upper() != "SETTLED"
                or previous.profit is None
                or float(previous.profit) >= 0
            ):
                db.rollback()
                return None
            expected_locked = self._three_trade_locked_target(row, db=db)
            if expected_locked is not None and int(digit) != int(expected_locked):
                db.rollback()
                return None

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

        # Guard the exact outbound parameters. A claim created for another
        # barrier may not be silently reused by an async buy continuation.
        if int(payload["digit"]) != int(claim["digit"]):
            raise RuntimeError("BUY_CLAIM_LOST: digit changed after claim")

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

        # Deriv's own purchase timestamp lets us distinguish some harmless
        # in-flight ticks from genuinely ambiguous ones.
        #
        # If the purchase timestamp is strictly AFTER the latest market tick
        # observed while BUY was in flight, then every such tick is provably
        # pre-purchase. In that case it is safe to keep the fast owner and arm
        # the contract after buy_ack_seq.
        #
        # If the timestamps are equal (whole-second resolution), unavailable,
        # or the market tick is later than the purchase timestamp, the ordering
        # cannot be proven. Only those cases fall back to official settlement.
        purchase_epoch = int(
            buy.get("purchase_time")
            or buy.get("start_time")
            or 0
        )

        inflight_proven_pre_purchase = bool(
            inflight_tick_count > 0
            and purchase_epoch > 0
            and buy_ack_epoch > 0
            and purchase_epoch > buy_ack_epoch
        )

        official_only_inflight = bool(
            inflight_tick_count > 0
            and not inflight_proven_pre_purchase
        )

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
                        "purchase_epoch": int(purchase_epoch or 0) or None,
                        "inflight_proven_pre_purchase": bool(
                            inflight_proven_pre_purchase
                        ),
                        "arming_policy": (
                            "OFFICIAL_ONLY_AMBIGUOUS_INFLIGHT_TICK"
                            if official_only_inflight
                            else (
                                "FIRST_NEW_SERVER_TICK_AFTER_BUY_ACK_"
                                "INFLIGHT_PROVEN_PRE_PURCHASE"
                                if inflight_tick_count > 0
                                else "FIRST_NEW_SERVER_TICK_AFTER_BUY_ACK"
                            )
                        ),
                    },
                }),
            )
        )

        # Exact callback sequence is authoritative for local fast ownership.
        # purchase_epoch was captured above from Deriv's BUY acknowledgement.
        # Fall back to buy_ack_epoch only for display/legacy epoch gating; the
        # ambiguity decision itself never treats that fallback as proof.
        decision_after_epoch = max(
            buy_ack_epoch,
            purchase_epoch or buy_ack_epoch,
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
            "inflight_proven_pre_purchase": bool(
                inflight_proven_pre_purchase
            ),
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
            "selector_source": score_evidence.get("selector_source"),
            "fusion": score_evidence.get("fusion"),
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
        #
        # If in-flight ticks did occur, keep fast ownership only when Deriv's
        # purchase timestamp proves all observed in-flight ticks were earlier
        # than the purchase. Same-second/unordered cases remain conservative and
        # wait for authoritative Deriv settlement.

        self._schedule_contract_subscription(
            sid=s.id,
            user_id=s.user_id,
            account_id=s.account_id,
            contract_id=contract_id,
            client=client,
        )

        return True

    def _schedule_contract_subscription(
        self,
        *,
        sid,
        user_id,
        account_id,
        contract_id,
        client,
    ):
        """
        Ensure at most ONE subscription-setup task exists for a contract.

        step() runs every ~20 ms. Without this registry, multiple worker passes
        can all see "no subscription yet" while the first Deriv subscription
        request is still in flight, causing a burst of duplicate
        proposal_open_contract requests for the same contract.
        """
        key = (int(sid), str(contract_id))

        if key in self.contract_subscriptions:
            return

        poll = self.contract_poll_tasks.get(key)
        if poll and not poll.done():
            return

        existing = self.contract_subscription_tasks.get(key)
        if existing and not existing.done():
            return

        async def runner():
            try:
                await self._subscribe_open_contract(
                    sid=sid,
                    user_id=user_id,
                    account_id=account_id,
                    contract_id=str(contract_id),
                    client=client,
                )
            finally:
                current = self.contract_subscription_tasks.get(key)
                if current is asyncio.current_task():
                    self.contract_subscription_tasks.pop(key, None)

        self.contract_subscription_tasks[key] = asyncio.create_task(runner())

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


    def _official_exit_digit(self, sid: int, poc: dict):
        """
        Return the authoritative last digit of Deriv's settled exit_spot.

        Prefer the exact string representation returned by Deriv so trailing
        zeroes are preserved. If Deriv returns a numeric value, format it with
        the market precision learned from the canonical tick stream.
        """
        raw = poc.get("exit_spot")
        if raw is None:
            return None

        if isinstance(raw, str):
            digits = [ch for ch in raw if ch.isdigit()]
            return int(digits[-1]) if digits else None

        decimals = self.tick_precision.get(int(sid))
        try:
            if decimals is not None:
                rendered = f"{float(raw):.{int(decimals)}f}"
            else:
                rendered = str(raw)
        except Exception:
            rendered = str(raw)

        digits = [ch for ch in rendered if ch.isdigit()]
        return int(digits[-1]) if digits else None

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
                        official_digit = self._official_exit_digit(int(sid), poc)
                        execution_state["official_result"] = official
                        execution_state["settlement_verified"] = True
                        execution_state["barrier_matches_exit_digit"] = (official_digit == int(execution_state["target_digit"]) if official_digit is not None else None)
                        execution_state["local_official_mismatch"] = (execution_state.get("local_result") != official if execution_state.get("local_result") is not None else None)
                        execution_state["official_exit_spot"] = poc.get("exit_spot")
                        execution_state["official_exit_spot_time"] = poc.get("exit_spot_time")
                        execution_state["official_decision_digit"] = official_digit

                        if execution_state.get("decision_mode") == "OFFICIAL_ONLY_INFLIGHT_TICK":
                            execution_state["decided"] = True
                            execution_state["decision_source"] = "DERIV_SETTLEMENT_EXIT_SPOT"
                            execution_state["local_result"] = None
                            if official_digit is not None:
                                execution_state["decision_digit"] = int(official_digit)

                        self.execution_contract_state[int(sid)] = execution_state
                        snapshot = self.digit_score_snapshots.get(int(sid))
                        if isinstance(snapshot, dict):
                            snapshot["execution_contract"] = json.loads(
                                json.dumps(execution_state)
                            )

                    if (
                        isinstance(execution_state, dict)
                        and str(execution_state.get("contract_id") or "") == str(contract_id)
                        and execution_state.get("local_result") == "WIN"
                        and s.phase == "LOCAL_MATCH_AWAITING_OFFICIAL"
                    ):
                        s.running = False
                        if execution_state.get("official_result") == "WIN":
                            s.phase = "OFFICIAL_WON"
                        else:
                            s.phase = "RECONCILE_MISMATCH"
                            s.last_error = f"Local/official disagreement for contract {contract_id}"
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
                    existing_raw["settlement_exit_spot"] = poc.get("exit_spot")
                    existing_raw["settlement_exit_spot_time"] = poc.get("exit_spot_time")
                    existing_raw["settlement_exit_digit"] = self._official_exit_digit(
                        int(sid),
                        poc,
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

                # DMS_RACE_GUARD_V11: settled WIN closes the cycle; official
                # settled LOSS is consumed only by the normal worker step.
                if profit > 0 and s.phase not in (
                    "RECONCILE_MISMATCH", "RECONCILE_TICK_MISMATCH"
                ):
                    s.running = False
                    s.paused = False
                    s.phase = "OFFICIAL_WON"
                # Stop on any disagreement between provisional result and
                # official payout. Never continue an inconsistent cycle.
                previous_fast = self.fast_contracts.get(sid)
                if (
                    previous_fast
                    and str(previous_fast.get("contract_id")) == str(contract_id)
                    and previous_fast.get("fast_result")
                    and previous_fast.get("fast_result") != ("WIN" if profit > 0 else "LOSS")
                ):
                    s.running = False
                    s.phase = "RECONCILE_MISMATCH"
                    s.last_error = f"Local/official outcome disagreement on {contract_id}"
                # No active fast-owner may strand the worker once settlement
                # has been durably recorded. Retire only this contract owner.
                active_owner = self.fast_contracts.get(sid)
                if active_owner and str(active_owner.get("contract_id")) == str(contract_id):
                    self.fast_contracts.pop(sid, None)

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
                    official_digit = self._official_exit_digit(int(sid), poc)
                    execution_state["official_result"] = official
                    execution_state["settlement_verified"] = True
                    execution_state["barrier_matches_exit_digit"] = (official_digit == int(execution_state["target_digit"]) if official_digit is not None else None)
                    execution_state["local_official_mismatch"] = (execution_state.get("local_result") != official if execution_state.get("local_result") is not None else None)
                    execution_state["official_exit_spot"] = poc.get("exit_spot")
                    execution_state["official_exit_spot_time"] = poc.get("exit_spot_time")
                    execution_state["official_decision_digit"] = official_digit

                    if execution_state.get("decision_mode") == "OFFICIAL_ONLY_INFLIGHT_TICK":
                        execution_state["decided"] = True
                        execution_state["decision_source"] = "DERIV_SETTLEMENT_EXIT_SPOT"
                        execution_state["local_result"] = None
                        if official_digit is not None:
                            execution_state["decision_digit"] = int(official_digit)
                    else:
                        # A public-feed next tick need not equal the exact Deriv
                        # exit tick. Preserve mismatch as a diagnostic only.
                        pass

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
                        "exit_spot": poc.get("exit_spot"),
                        "exit_spot_time": poc.get("exit_spot_time"),
                        "exit_digit": self._official_exit_digit(int(sid), poc),
                        "settled_at": datetime.utcnow().isoformat(),

                        # Exact cycle accounting from persisted Deriv settlements.
                        "cycle_pnl_authoritative": bool(
                            cycle_summary.get("authoritative")
                        ),
                        "cycle_pnl": cycle_summary.get("cycle_pnl"),
                        "cycle_total_stake": cycle_summary.get("cycle_stake"),
                        "cycle_trade_count": cycle_summary.get("cycle_trades"),
                    }

                    # Local market-tick decisions are observational only.
                    # Record disagreement in execution diagnostics instead of
                    # overriding Deriv's verified settlement.

                # Only the recorded Deriv settlement determines cycle outcome.
                # Public tick observations do not override this result.

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

                # V17: Deriv settlement is authoritative even if the local tick
                # callback has not run. Clear the exact settled owner so the
                # next worker iteration can progress from persisted TradeLog.
                active_fast = self.fast_contracts.get(sid)
                if (
                    active_fast
                    and str(active_fast.get("contract_id") or "")
                    == str(contract_id)
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

        # Event-driven resume: a confirmed settlement can make the following
        # worker step eligible immediately, without waiting for the next
        # session-discovery pass. step() takes the per-session lock and the
        # BUY path still requires the database claim, preventing duplicates.
        # An official WIN will already have stopped the cycle, so this is
        # harmless for wins and terminal reconciliation states.
        asyncio.create_task(self._safe_step(int(sid)))

    def last_settlement_status(self, sid: int):
        """Return the latest authoritative Deriv settlement for this session."""
        value = self.last_settlement_by_sid.get(int(sid))
        return dict(value) if isinstance(value, dict) else None

engine = MultiUserEngine()
