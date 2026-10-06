import asyncio
import json
import math
from collections import deque
from datetime import datetime

from .db import SessionLocal
from .models import (
    TradingSession,
    DerivCredential,
    DerivAccount,
    TradeLog,
    TAEState,
    TAEObservation,
)
from .security import decrypt_token
from .deriv_rest import get_ws_url
from .deriv_ws import DerivWS


class MultiUserEngine:
    """
    DigitMatchStar DEMO low-latency engine + V33 Persistent Target Attraction Engine.

    Strategy invariant:
      1. Buy Trade N.
      2. The first eligible live tick after the trade is armed drives the
         immediate strategy decision:
            target digit == tick last digit -> WIN -> stop immediately
            target digit != tick last digit -> LOSS -> advance immediately
      3. The next recovery proposal is pre-armed while Trade N is open.
      4. On a fast loss, BUY Trade N+1 immediately with that pre-armed proposal.
      5. Deriv proposal_open_contract settlement runs in the background only
         for authoritative P/L/accounting/reconciliation.
      6. If the fast tick result disagrees with Deriv's eventual settlement,
         stop with RECONCILE_MISMATCH rather than silently continuing.

    Automated execution remains DEMO-only.
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

        # Only the newest strategy-active paid contract belongs here.
        # Older contracts can still settle in the background.
        self.fast_contracts = {}  # sid -> contract metadata

        # Settlement bookkeeping keyed per individual contract.
        self.contract_subscriptions = {}  # (sid, contract_id) -> sub_id
        self.contract_subscription_tasks = {}  # (sid, contract_id) -> task
        self.contract_poll_tasks = {}  # low-frequency fallback only

        # One pre-armed recovery proposal per session.
        self.prefetched_recovery = {}  # sid -> payload
        self.prefetch_tasks = {}  # sid -> asyncio.Task

        # TARGET ATTRACTION ENGINE V1 — FORWARD-ONLY T10 RESEARCH
        #
        # This model does NOT alter or "pull" Deriv's RNG. It learns, from
        # already-matured live observations only, which pre-entry contexts are
        # associated with the selected target digit recurring within 10 future
        # ticks. Trade 1 is armed only when the model is sufficiently trained
        # and the current forward-only score exceeds the frozen threshold.
        self.tick_digit_history = {}      # sid -> deque(maxlen=100)
        self.tae_pending = {}             # sid -> list of unresolved samples
        self.tae_models = {}              # sid -> model state
        self.tae_records = {}             # sid -> recent matured observations
        self.target_digit_by_sid = {}     # sid -> currently selected digit
        self.tae_loaded = set()           # sessions restored from DB
        self.tae_ticks_since_persist = {} # lightweight history persistence cadence

        self.tae_horizon = 10
        self.tae_min_history = 100
        self.tae_min_train_samples = 250
        self.tae_arm_probability = 0.80
        self.tae_learning_rate = 0.035
        self.tae_l2 = 0.001

        # Frozen SAFE-TICK V1 is retained as ONE INPUT FEATURE, not as a hard
        # gate, so the new model can be tested independently.
        self.safe_v1_freq25_max = 0.08
        self.safe_v1_entropy10_max = 2.5219280948873625

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

                # Proposal throttling is recoverable. Do not convert it into a
                # fatal SERVER ERROR and destroy the session.
                if "ratelimit" in lower or "rate limit" in lower:
                    s.running = True
                    s.paused = False
                    s.last_error = message
                    s.phase = "RATE_LIMIT_BACKOFF"
                    s.updated_at = datetime.utcnow()
                    db.commit()

                    # Return control after a short pause. The orchestration loop
                    # can retry later; this task never remains stuck forever.
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

    def _history(self, sid: int):
        if sid not in self.tae_loaded:
            self._load_tae_state(sid)

        history = self.tick_digit_history.get(sid)
        if history is None:
            history = deque(maxlen=100)
            self.tick_digit_history[sid] = history
        return history

    @staticmethod
    def _entropy(values):
        n = len(values)
        if n <= 0:
            return 0.0

        counts = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1

        result = 0.0
        for count in counts.values():
            p = count / n
            result -= p * math.log2(p)

        return result

    @staticmethod
    def _sigmoid(value):
        if value >= 0:
            z = math.exp(-value)
            return 1.0 / (1.0 + z)
        z = math.exp(value)
        return z / (1.0 + z)

    def _default_tae_model(self):
        baseline = 1.0 - (0.9 ** self.tae_horizon)
        bias = math.log(baseline / (1.0 - baseline))

        return {
            "weights": [0.0] * 12,
            "bias": bias,
            "trained": 0,
            "positives": 0,
            "brier_sum": 0.0,
            "forward_predictions": 0,
            "forward_hits": 0,
            "selected_predictions": 0,
            "selected_hits": 0,
            "last_probability": None,
            "last_features": None,
            "last_target": None,
        }

    def _load_tae_state(self, sid: int):
        if sid in self.tae_loaded:
            return

        db = SessionLocal()
        try:
            row = (
                db.query(TAEState)
                .filter(TAEState.trading_session_id == sid)
                .first()
            )

            if row:
                try:
                    model = json.loads(row.model_json or "{}")
                except Exception:
                    model = {}

                default = self._default_tae_model()
                default.update(
                    {
                        k: v
                        for k, v in model.items()
                        if k in default
                    }
                )

                weights = default.get("weights")
                if not isinstance(weights, list) or len(weights) != 12:
                    default["weights"] = [0.0] * 12

                self.tae_models[sid] = default

                try:
                    history = json.loads(row.history_json or "[]")
                except Exception:
                    history = []

                cleaned = []
                for value in history[-100:]:
                    try:
                        digit = int(value)
                    except Exception:
                        continue
                    if 0 <= digit <= 9:
                        cleaned.append(digit)

                self.tick_digit_history[sid] = deque(
                    cleaned,
                    maxlen=100,
                )

                if row.target_digit is not None:
                    self.target_digit_by_sid[sid] = int(row.target_digit)

            else:
                self.tae_models[sid] = self._default_tae_model()
                self.tick_digit_history.setdefault(
                    sid,
                    deque(maxlen=100),
                )

            # Never restore pending forward labels after process downtime.
            # Missing ticks would make them non-contiguous and scientifically
            # invalid, so restart with a clean pending queue.
            self.tae_pending[sid] = []
            self.tae_loaded.add(sid)

        finally:
            db.close()

    def _persist_tae_state(self, sid: int):
        self._load_tae_state(sid)

        db = SessionLocal()
        try:
            session = db.get(TradingSession, sid)
            if not session:
                return

            row = (
                db.query(TAEState)
                .filter(TAEState.trading_session_id == sid)
                .first()
            )

            if row is None:
                row = TAEState(
                    trading_session_id=sid,
                    user_id=session.user_id,
                    account_id=session.account_id,
                    symbol=session.symbol,
                )
                db.add(row)

            row.user_id = session.user_id
            row.account_id = session.account_id
            row.symbol = session.symbol
            row.target_digit = self.target_digit_by_sid.get(sid)
            row.model_json = json.dumps(
                self._tae_model(sid),
                separators=(",", ":"),
            )
            row.history_json = json.dumps(
                list(self._history(sid)),
                separators=(",", ":"),
            )
            row.updated_at = datetime.utcnow()

            db.commit()
        finally:
            db.close()

    def _persist_tae_observation(self, sid: int, record: dict):
        db = SessionLocal()
        try:
            session = db.get(TradingSession, sid)
            if not session:
                return

            existing = (
                db.query(TAEObservation)
                .filter(
                    TAEObservation.trading_session_id == sid,
                    TAEObservation.sample_index
                    == int(record["sample_index"]),
                )
                .first()
            )

            if existing is None:
                db.add(
                    TAEObservation(
                        trading_session_id=sid,
                        user_id=session.user_id,
                        account_id=session.account_id,
                        symbol=session.symbol,
                        sample_index=int(record["sample_index"]),
                        target_digit=int(record["target_digit"]),
                        prediction_t0_probability=float(
                            record["prediction_t0_probability"]
                        ),
                        selected=bool(record["selected"]),
                        arm_threshold=float(record["arm_threshold"]),
                        label_return_by_t10=int(
                            record["label_return_by_t10"]
                        ),
                        stop10=int(record["stop10"]),
                        forward_gap=(
                            int(record["forward_gap"])
                            if record.get("forward_gap") is not None
                            else None
                        ),
                        horizon=int(record["horizon"]),
                        features_json=json.dumps(
                            list(record["features"]),
                            separators=(",", ":"),
                        ),
                        model_trained_samples_at_t0=int(
                            record["model_trained_samples_at_t0"]
                        ),
                    )
                )

            db.commit()
        finally:
            db.close()

    def _tae_model(self, sid: int):
        self._load_tae_state(sid)

        model = self.tae_models.get(sid)
        if model is None:
            model = self._default_tae_model()
            self.tae_models[sid] = model

        return model

    def _tae_features(self, sid: int, target_digit: int):
        history = list(self._history(sid))
        if len(history) < self.tae_min_history:
            return None

        target_digit = int(target_digit)

        def freq(window):
            values = history[-window:]
            if not values:
                return 0.0
            return sum(1 for d in values if d == target_digit) / len(values)

        # Gap since most recent target, capped at 50 and scaled to [0,1].
        gap = 50
        for i, digit in enumerate(reversed(history), start=0):
            if digit == target_digit:
                gap = min(i, 50)
                break

        last10 = history[-10:]
        last25 = history[-25:]
        last50 = history[-50:]
        last100 = history[-100:]

        entropy10 = self._entropy(last10) / math.log2(10)
        entropy25 = self._entropy(last25) / math.log2(10)

        adjacent_repeats = 0.0
        if len(last10) > 1:
            adjacent_repeats = (
                sum(
                    1
                    for a, b in zip(last10[:-1], last10[1:])
                    if a == b
                )
                / (len(last10) - 1)
            )

        # Empirical transition P(next == target | current digit), calculated
        # only from history that already existed before the future label.
        current_digit = history[-1]
        transition_total = 0
        transition_hits = 0
        for a, b in zip(last100[:-1], last100[1:]):
            if a == current_digit:
                transition_total += 1
                if b == target_digit:
                    transition_hits += 1

        transition_to_target = (
            transition_hits / transition_total
            if transition_total
            else 0.10
        )

        freq25 = freq(25)
        safe_v1 = 1.0 if (
            freq25 <= self.safe_v1_freq25_max
            and self._entropy(last10) <= self.safe_v1_entropy10_max
        ) else 0.0

        return [
            gap / 50.0,
            freq(5),
            freq(10),
            freq25,
            freq(50),
            freq(100),
            entropy10,
            entropy25,
            adjacent_repeats,
            transition_to_target,
            1.0 if current_digit == target_digit else 0.0,
            safe_v1,
        ]

    def _tae_predict_from_features(self, sid: int, features):
        model = self._tae_model(sid)
        score = model["bias"]
        for weight, value in zip(model["weights"], features):
            score += weight * value
        return self._sigmoid(score)

    def _tae_train_one(self, sid: int, features, label: int, predicted: float):
        model = self._tae_model(sid)
        n = model["trained"] + 1

        # Gentle decay avoids increasingly large late updates while keeping the
        # model adaptive to newly observed forward data.
        lr = self.tae_learning_rate / math.sqrt(1.0 + n / 250.0)
        error = float(label) - float(predicted)

        model["bias"] += lr * error

        new_weights = []
        for weight, value in zip(model["weights"], features):
            gradient = error * value - self.tae_l2 * weight
            new_weights.append(weight + lr * gradient)

        model["weights"] = new_weights
        model["trained"] = n
        model["positives"] += int(label)
        model["brier_sum"] += (float(predicted) - float(label)) ** 2

    def _tae_observe_tick(self, sid: int, digit: int):
        """
        Advance old samples with this NEW tick, mature labels at exactly T10,
        train only on those matured labels, then append this tick to history
        and create a new strictly-forward sample.

        There is no future leakage: each prediction is made before its next
        ten ticks exist.
        """
        target = self.target_digit_by_sid.get(sid)
        if target is None:
            self._history(sid).append(int(digit))
            return

        pending = self.tae_pending.setdefault(sid, [])
        still_pending = []

        for sample in pending:
            sample["ticks_observed"] = int(sample.get("ticks_observed") or 0) + 1

            if (
                not sample.get("hit")
                and int(digit) == int(sample["target"])
            ):
                sample["hit"] = True
                sample["forward_gap"] = int(sample["ticks_observed"])

            sample["remaining"] -= 1

            if sample["remaining"] <= 0:
                label = 1 if sample["hit"] else 0
                predicted = float(sample["predicted"])

                self._tae_train_one(
                    sid,
                    sample["features"],
                    label,
                    predicted,
                )

                model = self._tae_model(sid)
                model["forward_predictions"] += 1
                model["forward_hits"] += label

                if sample["selected"]:
                    model["selected_predictions"] += 1
                    model["selected_hits"] += label

                records = self.tae_records.setdefault(sid, [])

                record = {
                    # forward_predictions is incremented immediately above and
                    # is persisted, so this remains unique across redeploys.
                    "sample_index": int(model["forward_predictions"]),
                    "target_digit": int(sample["target"]),
                    "prediction_t0_probability": predicted,
                    "selected": bool(sample["selected"]),
                    "arm_threshold": float(self.tae_arm_probability),
                    "label_return_by_t10": int(label),
                    "stop10": int(not bool(label)),
                    "forward_gap": (
                        int(sample["forward_gap"])
                        if sample.get("forward_gap") is not None
                        else None
                    ),
                    "horizon": int(self.tae_horizon),
                    "features": list(sample["features"]),
                    "model_trained_samples_at_t0": int(
                        sample.get("trained_at_t0") or 0
                    ),
                }

                records.append(record)
                if len(records) > 1000:
                    del records[:-1000]

                # Persist every matured observation AND the updated model.
                # This is the research checkpoint that survives Render
                # redeploys/restarts when the configured database persists.
                self._persist_tae_observation(sid, record)
                self._persist_tae_state(sid)
            else:
                still_pending.append(sample)

        self.tae_pending[sid] = still_pending

        self._history(sid).append(int(digit))

        self.tae_ticks_since_persist[sid] = (
            int(self.tae_ticks_since_persist.get(sid) or 0) + 1
        )
        if self.tae_ticks_since_persist[sid] >= 10:
            self.tae_ticks_since_persist[sid] = 0
            self._persist_tae_state(sid)

        features = self._tae_features(sid, int(target))
        if features is None:
            return

        model = self._tae_model(sid)
        predicted = self._tae_predict_from_features(sid, features)

        selected = (
            model["trained"] >= self.tae_min_train_samples
            and predicted >= self.tae_arm_probability
        )

        model["last_probability"] = predicted
        model["last_features"] = list(features)
        model["last_target"] = int(target)

        pending.append(
            {
                "target": int(target),
                "features": list(features),
                "predicted": predicted,
                "remaining": self.tae_horizon,
                "ticks_observed": 0,
                "hit": False,
                "forward_gap": None,
                "selected": bool(selected),
                "trained_at_t0": int(model["trained"]),
            }
        )

    def target_attraction_status(self, sid: int):
        model = self._tae_model(sid)
        trained = int(model["trained"])
        selected = int(model["selected_predictions"])
        forward_n = int(model["forward_predictions"])
        history_n = len(self._history(sid))
        pending = list(self.tae_pending.get(sid, []))

        next_maturity = None
        if pending:
            next_maturity = min(
                int(sample.get("remaining") or self.tae_horizon)
                for sample in pending
            )

        return {
            "name": "TARGET_ATTRACTION_ENGINE_V1",
            "version": "V33-PERSISTENT",
            "horizon": self.tae_horizon,
            "minimum_history": self.tae_min_history,
            "history_count": history_n,
            "history_ready": history_n >= self.tae_min_history,
            "pending_observations": len(pending),
            "next_sample_matures_in_ticks": next_maturity,
            "min_train_samples": self.tae_min_train_samples,
            "arm_probability": self.tae_arm_probability,
            "trained_samples": trained,
            "training_progress": min(
                1.0,
                trained / self.tae_min_train_samples
                if self.tae_min_train_samples else 1.0,
            ),
            "positive_rate": (
                model["positives"] / trained
                if trained else None
            ),
            "brier_score": (
                model["brier_sum"] / trained
                if trained else None
            ),
            "forward_predictions": forward_n,
            "forward_hit_rate": (
                model["forward_hits"] / forward_n
                if forward_n else None
            ),
            "selected_predictions": selected,
            "selected_hit_rate": (
                model["selected_hits"] / selected
                if selected else None
            ),
            "selected_stop10_rate": (
                (selected - model["selected_hits"]) / selected
                if selected else None
            ),
            "current_target": model["last_target"],
            "current_probability_t10": model["last_probability"],
            "ready": trained >= self.tae_min_train_samples,
            "armed_now": bool(
                trained >= self.tae_min_train_samples
                and model["last_probability"] is not None
                and model["last_probability"] >= self.tae_arm_probability
            ),
            "persistent": True,
            "persistence_note": (
                "Matured observations and model state are stored in the "
                "configured database. Unresolved T10 samples are discarded "
                "after a process restart because continuity was interrupted."
            ),
            "note": (
                "Forward-only research score. It estimates recurrence within "
                "10 ticks; it does not control or alter Deriv's RNG."
            ),
        }

    def export_target_attraction(self, sid: int):
        """
        Export persisted matured forward observations plus live model status.
        """
        status = self.target_attraction_status(sid)

        db = SessionLocal()
        try:
            rows = (
                db.query(TAEObservation)
                .filter(TAEObservation.trading_session_id == sid)
                .order_by(TAEObservation.sample_index.asc())
                .all()
            )

            records = []
            for row in rows:
                try:
                    features = json.loads(row.features_json or "[]")
                except Exception:
                    features = []

                records.append(
                    {
                        "sample_index": int(row.sample_index),
                        "target_digit": int(row.target_digit),
                        "prediction_t0_probability": float(
                            row.prediction_t0_probability
                        ),
                        "selected": bool(row.selected),
                        "arm_threshold": float(row.arm_threshold),
                        "label_return_by_t10": int(
                            row.label_return_by_t10
                        ),
                        "stop10": int(row.stop10),
                        "forward_gap": (
                            int(row.forward_gap)
                            if row.forward_gap is not None
                            else None
                        ),
                        "horizon": int(row.horizon),
                        "features": features,
                        "model_trained_samples_at_t0": int(
                            row.model_trained_samples_at_t0
                        ),
                        "created_at": (
                            row.created_at.isoformat()
                            if row.created_at
                            else None
                        ),
                    }
                )
        finally:
            db.close()

        feature_names = [
            "gap_since_target_scaled",
            "target_freq5",
            "target_freq10",
            "target_freq25",
            "target_freq50",
            "target_freq100",
            "entropy10_normalized",
            "entropy25_normalized",
            "adjacent_repeat_rate10",
            "transition_current_to_target",
            "current_digit_equals_target",
            "safe_tick_v1_accept_flag",
        ]

        return {
            "schema": "DIGITMATCHSTAR_TARGET_ATTRACTION_ENGINE_V1_EXPORT",
            "version": "V33-PERSISTENT-TAE-2026-10-06",
            "forward_only": True,
            "persistent_database": True,
            "horizon_ticks": int(self.tae_horizon),
            "feature_names": feature_names,
            "entry_policy": {
                "minimum_history": int(self.tae_min_history),
                "minimum_matured_training_samples": int(
                    self.tae_min_train_samples
                ),
                "arm_probability": float(self.tae_arm_probability),
            },
            "status": status,
            "records_count": len(records),
            "pending_count": len(self.tae_pending.get(sid, [])),
            "records": records,
            "note": (
                "Matured observations are persisted in the configured database. "
                "Pending observations are intentionally not restored after a "
                "server restart because strict tick continuity was interrupted."
            ),
        }

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
            existing_id = existing.get("subscription_id")

            # IMPORTANT: engine memory can outlive a WebSocket reconnect.
            # If DerivWS reconnects (for example after a proposal timeout),
            # the old subscription id no longer exists on the new socket.
            # Do not trust the engine-side id unless the CURRENT socket still
            # owns it.
            if (
                existing_id
                and client.has_subscription(existing_id)
            ):
                return

            # Stale subscription marker: remove it and subscribe again now.
            self.tick_subscriptions.pop(sid, None)
            existing = None

        if existing:
            old_id = existing.get("subscription_id")
            if old_id and client.has_subscription(old_id):
                asyncio.create_task(
                    self._forget_quietly(client, old_id)
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

        # Feed every live tick into the forward-only Target Attraction Engine,
        # including periods when no paid contract is active.
        digit = self._tick_last_digit(tick)
        if digit is not None:
            self._tae_observe_tick(sid, int(digit))

        active = self.fast_contracts.get(sid)

        if active:
            # Any live tick proves that the tick stream itself is healthy.
            active["last_tick_seen_loop_time"] = (
                asyncio.get_running_loop().time()
            )

        if not active:
            return

        if str(active.get("symbol")) != str(symbol):
            return

        if active.get("decided"):
            return

        armed_after_epoch = int(active.get("armed_after_epoch") or 0)

        # The strategy only considers a tick newer than the tick/purchase epoch
        # that existed when BUY was armed.
        if epoch and armed_after_epoch and epoch <= armed_after_epoch:
            return

        if digit is None:
            return

        # Mark synchronously before any await. Duplicate tick callbacks cannot
        # advance this same contract twice.
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
                    self.prefetched_recovery.pop(sid, None)

                    prefetch_task = self.prefetch_tasks.pop(sid, None)
                    if prefetch_task and not prefetch_task.done():
                        prefetch_task.cancel()

                    s.running = False
                    s.paused = False
                    s.phase = "FAST_WON"
                    s.last_error = None
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                # NO MATCH: immediate local strategy LOSS.
                #
                # This is the point where the next recovery advances. Official
                # Deriv settlement of Trade N is NOT awaited.
                if int(s.current_trade) >= int(s.max_trades):
                    self.prefetched_recovery.pop(sid, None)

                    prefetch_task = self.prefetch_tasks.pop(sid, None)
                    if prefetch_task and not prefetch_task.done():
                        prefetch_task.cancel()

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

                expected_trade_no = int(s.current_trade) + 1
                payload = self.prefetched_recovery.pop(sid, None)

                # Wait briefly for the ONE prefetch already in flight.
                #
                # Never wait forever: if Deriv has stalled the proposal request,
                # cancel that prefetch cleanly before making one fresh fallback.
                # This avoids both UI hangs and duplicate simultaneous proposals.
                if not payload:
                    prefetch_task = self.prefetch_tasks.get(sid)

                    if prefetch_task and not prefetch_task.done():
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(prefetch_task),
                                timeout=1.25,
                            )
                        except asyncio.TimeoutError:
                            prefetch_task.cancel()
                            try:
                                await prefetch_task
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                pass
                        except Exception:
                            pass

                        payload = self.prefetched_recovery.pop(sid, None)

                valid_prefetch = bool(
                    payload
                    and int(payload.get("trade_no") or 0)
                    == expected_trade_no
                    and int(payload.get("digit"))
                    == int(s.candidate_digit)
                    and abs(
                        float(payload.get("stake") or 0)
                        - float(s.current_stake)
                    ) <= 0.005
                )

                if not valid_prefetch:
                    # Only one fresh fallback proposal is allowed, and
                    # DerivWS serializes/rate-limits it globally per socket.
                    s.phase = "RECOVERY_PROPOSAL_FALLBACK"
                    s.updated_at = datetime.utcnow()
                    db.commit()

                    currency = await self._currency_for(db, s)
                    client = await self._client(user_id, account_id)

                    payload = await self._request_proposal_payload(
                        client,
                        symbol=s.symbol,
                        digit=s.candidate_digit,
                        stake=s.current_stake,
                        trade_no=expected_trade_no,
                        currency=currency,
                    )

                # LOSS -> immediate next BUY.
                #
                # No proposal_open_contract.is_sold wait occurs here.
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

                if s.candidate_digit is not None:
                    previous_target = self.target_digit_by_sid.get(sid)
                    current_target = int(s.candidate_digit)
                    self.target_digit_by_sid[sid] = current_target

                    if previous_target != current_target:
                        self._persist_tae_state(sid)

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

                # An open contract must never send the worker back into a
                # foreground WAITING_SETTLEMENT state.
                if s.open_contract_id:
                    contract_key = (
                        sid,
                        str(s.open_contract_id),
                    )

                    existing_contract_sub = self.contract_subscriptions.get(
                        contract_key
                    )
                    existing_contract_task = self.contract_subscription_tasks.get(
                        contract_key
                    )

                    if (
                        (
                            not existing_contract_sub
                            or not client.has_subscription(
                                existing_contract_sub
                            )
                        )
                        and (
                            not existing_contract_task
                            or existing_contract_task.done()
                        )
                        and contract_key not in self.contract_poll_tasks
                    ):
                        task = asyncio.create_task(
                            self._subscribe_open_contract(
                                sid=sid,
                                user_id=s.user_id,
                                account_id=s.account_id,
                                contract_id=str(s.open_contract_id),
                                client=client,
                            )
                        )
                        self.contract_subscription_tasks[
                            contract_key
                        ] = task

                    # PIPELINE watchdog:
                    # if no result tick has been consumed for >3.5 seconds,
                    # the most likely cause is a stale/lost tick subscription
                    # after a WebSocket reconnect. Force a clean re-subscribe.
                    fast = self.fast_contracts.get(sid)
                    if fast and not fast.get("decided"):
                        armed_at = float(
                            fast.get("armed_at_loop_time") or 0.0
                        )
                        age = (
                            asyncio.get_running_loop().time() - armed_at
                            if armed_at
                            else 0.0
                        )

                        if age > 3.5:
                            stale = self.tick_subscriptions.pop(
                                sid,
                                None,
                            )
                            stale_id = (
                                stale.get("subscription_id")
                                if stale
                                else None
                            )

                            if (
                                stale_id
                                and client.has_subscription(stale_id)
                            ):
                                asyncio.create_task(
                                    self._forget_quietly(
                                        client,
                                        stale_id,
                                    )
                                )

                            await self._ensure_tick_subscription(
                                sid=s.id,
                                user_id=s.user_id,
                                account_id=s.account_id,
                                symbol=s.symbol,
                                client=client,
                            )

                            # Reset watchdog only after a real resubscribe.
                            fast["armed_at_loop_time"] = (
                                asyncio.get_running_loop().time()
                            )

                            s.phase = "PIPELINE_RESUBSCRIBED"
                            s.updated_at = datetime.utcnow()
                            db.commit()
                            return

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

                # Keep unattended execution DEMO-only.
                if str(s.account_mode).upper() != "DEMO":
                    s.running = False
                    s.phase = "REAL_AUTOMATION_DISABLED"
                    s.last_error = (
                        "Automated server execution is DEMO-only in this build."
                    )
                    s.updated_at = datetime.utcnow()
                    db.commit()
                    return

                # TARGET ATTRACTION ENGINE — TRADE 1 GATE
                #
                # Once a cycle starts, recovery remains immediate. This gate
                # never delays Trade 2+ and settlement stays background-only.
                if int(s.current_trade) == 0:
                    model = self._tae_model(s.id)
                    trained = int(model["trained"])
                    probability = model["last_probability"]

                    if len(self._history(s.id)) < self.tae_min_history:
                        s.phase = "TAE_HISTORY_WARMING"
                        s.last_error = (
                            "Target Attraction collecting live history "
                            f"({len(self._history(s.id))}/{self.tae_min_history})"
                        )
                        s.updated_at = datetime.utcnow()
                        db.commit()
                        return

                    if trained < self.tae_min_train_samples:
                        s.phase = "TAE_MODEL_WARMING"
                        s.last_error = (
                            "Target Attraction forward-training "
                            f"({trained}/{self.tae_min_train_samples})"
                        )
                        s.updated_at = datetime.utcnow()
                        db.commit()
                        return

                    if probability is None:
                        s.phase = "TAE_SCORING"
                        s.last_error = "Target Attraction waiting for live score"
                        s.updated_at = datetime.utcnow()
                        db.commit()
                        return

                    if probability < self.tae_arm_probability:
                        s.phase = "TAE_WAITING"
                        s.last_error = (
                            f"Target {int(s.candidate_digit)} · "
                            f"P(return<=T10)={probability:.1%} · "
                            f"arm at {self.tae_arm_probability:.0%}"
                        )
                        s.updated_at = datetime.utcnow()
                        db.commit()
                        return

                    s.phase = "TAE_ARMED"
                    s.last_error = (
                        f"Target {int(s.candidate_digit)} · "
                        f"P(return<=T10)={probability:.1%} · ARMED"
                    )
                    s.updated_at = datetime.utcnow()
                    db.commit()

                currency = await self._currency_for(db, s)

                # Normal first trade of the cycle. Recovery trades normally use
                # the pre-armed path directly from _handle_strategy_tick().
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
                        "PROPOSAL "
                        f"[{s.symbol}/{currency}/digit {s.candidate_digit}]: "
                        f"{exc}"
                    ) from exc

                await self._execute_demo_buy(
                    db,
                    s,
                    client,
                    payload,
                    prearmed=False,
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
            raise RuntimeError(
                "Automated purchase blocked outside DEMO mode"
            )

        await self._ensure_tick_subscription(
            sid=s.id,
            user_id=s.user_id,
            account_id=s.account_id,
            symbol=s.symbol,
            client=client,
        )

        s.phase = (
            "BUYING_PREARMED"
            if prearmed
            else "BUYING"
        )
        s.updated_at = datetime.utcnow()
        db.commit()

        # Snapshot the newest tick before BUY. This prevents a tick that already
        # existed before purchase from being treated as this contract's result.
        armed_after_epoch = int(
            self.latest_tick_epoch.get(s.id) or 0
        )

        result = await client.buy(
            payload["proposal_id"],
            payload["ask_price"],
            demo=True,
        )

        buy = result.get("buy") or {}

        if not buy.get("contract_id"):
            raise RuntimeError(
                "BUY: Deriv returned no contract_id; "
                f"keys={list(result.keys())}"
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
                    buy.get("buy_price")
                    or payload["ask_price"]
                ),
                payout=payload["payout"],
                raw_json=json.dumps(result),
            )
        )

        purchase_epoch = int(
            buy.get("start_time")
            or buy.get("purchase_time")
            or armed_after_epoch
            or 0
        )

        decision_after_epoch = max(
            armed_after_epoch,
            purchase_epoch,
        )

        # This is now the only contract whose next eligible live tick may drive
        # strategy advancement.
        self.fast_contracts[s.id] = {
            "contract_id": contract_id,
            "target_digit": int(payload["digit"]),
            "symbol": str(s.symbol),
            "trade_no": int(payload["trade_no"]),
            "armed_after_epoch": decision_after_epoch,
            "armed_at_loop_time": asyncio.get_running_loop().time(),
            "decided": False,
        }

        # open_contract_id is allowed to point to the newest contract while
        # older contracts reconcile independently by their own contract IDs.
        s.open_contract_id = contract_id
        s.phase = "PIPELINE_ACTIVE"
        s.current_trade += 1
        s.pending_trade_json = None
        s.pending_real_confirmation = False
        s.last_error = None
        s.updated_at = datetime.utcnow()
        db.commit()

        # A live tick can arrive while the BUY response is travelling back.
        # If that happened, immediately feed the cached newer tick into the
        # strategy instead of waiting for yet another tick.
        cached_tick = self.latest_ticks.get(s.id)

        if cached_tick:
            cached_epoch = int(
                cached_tick.get("epoch") or 0
            )

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

        # Pre-arm exactly ONE proposal for the next recovery while this trade is
        # active. The proposal request is outside the result-critical path.
        if s.current_trade < s.max_trades:
            existing = self.prefetch_tasks.get(s.id)

            if not existing or existing.done():
                task = asyncio.create_task(
                    self._prefetch_next_recovery(
                        sid=s.id,
                        user_id=s.user_id,
                        account_id=s.account_id,
                        symbol=s.symbol,
                        digit=int(s.candidate_digit),
                        next_stake=round(
                            float(s.current_stake)
                            * float(s.multiplier),
                            2,
                        ),
                        next_trade_no=int(s.current_trade) + 1,
                    )
                )

                self.prefetch_tasks[s.id] = task

        # Official settlement is background accounting/reconciliation only.
        contract_key = (
            s.id,
            str(contract_id),
        )

        existing_contract_task = self.contract_subscription_tasks.get(
            contract_key
        )

        if (
            not existing_contract_task
            or existing_contract_task.done()
        ):
            task = asyncio.create_task(
                self._subscribe_open_contract(
                    sid=s.id,
                    user_id=s.user_id,
                    account_id=s.account_id,
                    contract_id=contract_id,
                    client=client,
                )
            )
            self.contract_subscription_tasks[
                contract_key
            ] = task

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
            client = await self._client(
                user_id,
                account_id,
            )

            db = SessionLocal()

            try:
                s = db.get(TradingSession, sid)

                if (
                    not s
                    or not s.running
                    or not s.open_contract_id
                ):
                    return

                currency = await self._currency_for(
                    db,
                    s,
                )

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

            db = SessionLocal()

            try:
                s = db.get(TradingSession, sid)

                # Keep only a proposal that still belongs to the exact next
                # trade of the currently running session.
                if (
                    s
                    and s.running
                    and s.open_contract_id
                    and int(s.current_trade) + 1
                    == int(next_trade_no)
                ):
                    self.prefetched_recovery[sid] = payload
                    s.phase = "RECOVERY_PREARMED"
                    s.updated_at = datetime.utcnow()
                    db.commit()

            finally:
                db.close()

        except asyncio.CancelledError:
            raise

        except Exception:
            # Prefetch is an optimization. A later recovery may safely obtain
            # one fresh proposal through the serialized proposal lane.
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
        key = (
            sid,
            str(contract_id),
        )

        existing_sub_id = self.contract_subscriptions.get(key)

        if existing_sub_id:
            if client.has_subscription(existing_sub_id):
                self.contract_subscription_tasks.pop(key, None)
                return

            # Socket was reconnected and this id belongs to the dead socket.
            self.contract_subscriptions.pop(key, None)

        if key in self.contract_poll_tasks:
            self.contract_subscription_tasks.pop(key, None)
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
            self.contract_subscription_tasks.pop(key, None)
            return

        # Fallback only if Deriv does not return a subscription id for the
        # very short-lived 1-tick contract.
        #
        # CRITICAL RATE-LIMIT FIX:
        # proposal_open_contract shares Deriv's trading-call request budget
        # with proposal/buy/sell. The previous 0.20-second loop could consume
        # hundreds of requests per minute and starve the actual trading path.
        #
        # Strategy does NOT depend on this reconciliation. Therefore perform
        # only a few delayed checks, well outside the critical execution path.
        async def reconcile_later():
            try:
                # R_10 is roughly a 2-second tick market. By 2.5 seconds a
                # one-tick contract should normally have settled.
                delays = (2.5, 3.0, 5.0)

                for delay in delays:
                    await asyncio.sleep(delay)

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
                # Background reconciliation failure must never freeze or
                # throttle the live tick-driven strategy.
                return

            finally:
                self.contract_poll_tasks.pop(
                    key,
                    None,
                )

        self.contract_poll_tasks[key] = asyncio.create_task(
            reconcile_later()
        )
        self.contract_subscription_tasks.pop(key, None)

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
                # Account each contract exactly once.
                if (
                    log
                    and str(log.status).upper() == "SETTLED"
                ):
                    return

                profit = float(
                    poc.get("profit") or 0
                )

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

                if (
                    fast
                    and str(fast.get("contract_id"))
                    == str(contract_id)
                ):
                    official = (
                        "WIN"
                        if profit > 0
                        else "LOSS"
                    )

                    fast["official_result"] = official

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

                s.updated_at = datetime.utcnow()
                db.commit()

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

    async def confirm_real(self, user_id: str, session_id: int):
        raise RuntimeError(
            "Automated REAL-money execution is disabled "
            "in this low-latency build."
        )


engine = MultiUserEngine()
