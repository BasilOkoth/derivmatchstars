from __future__ import annotations

import math
from collections import Counter


class DigitScoreEngine:
    """
    DigitScore V1 Stable Execution + Trigger Fusion Shadow Research.

    EXECUTION:
    - Uses the original V1 relative score only.
    - No Trigger Fusion bonus may change the executed target.
    - No hard score threshold.
    - Same target is held for the active 3-trade block.

    SHADOW:
    - Trend velocity / dominance / break / alternating-pair signals are
      calculated separately for research and export only.
    """

    VERSION = "DIGIT_SCORE_V1_STABLE"
    SHADOW_VERSION = "TRIGGER_FUSION_SHADOW_V1"

    def __init__(
        self,
        recycle_after: int = 3,
        min_history: int = 10,
        max_history: int = 100,
    ):
        self.recycle_after = max(1, int(recycle_after))
        self.min_history = max(5, int(min_history))
        self.max_history = max(self.min_history, int(max_history))

    @staticmethod
    def _entropy(values):
        values = list(values)
        if not values:
            return 0.0
        counts = Counter(values)
        n = len(values)
        return -sum((c / n) * math.log2(c / n) for c in counts.values())

    @staticmethod
    def _freq(history, digit, window):
        values = history[-window:]
        return sum(1 for d in values if d == digit) / len(values) if values else 0.0

    @staticmethod
    def _gap(history, digit, cap=50):
        for i, d in enumerate(reversed(history)):
            if d == digit:
                return min(i, cap)
        return cap

    @staticmethod
    def _transition1(history, digit):
        if len(history) < 2:
            return 0.10
        current = history[-1]
        total = hits = 0
        for a, b in zip(history[:-1], history[1:]):
            if a == current:
                total += 1
                hits += int(b == digit)
        return (hits + 1.0) / (total + 10.0)

    @staticmethod
    def _transition2(history, digit):
        if len(history) < 3:
            return 0.10
        key = (history[-2], history[-1])
        total = hits = 0
        for i in range(len(history) - 2):
            if (history[i], history[i + 1]) == key:
                total += 1
                hits += int(history[i + 2] == digit)
        return (hits + 1.0) / (total + 10.0)

    @staticmethod
    def _linear_slope(values):
        values = [float(x) for x in values]
        n = len(values)
        if n < 2:
            return 0.0
        xm = (n - 1) / 2.0
        ym = sum(values) / n
        den = sum((i - xm) ** 2 for i in range(n))
        if not den:
            return 0.0
        return sum((i - xm) * (y - ym) for i, y in enumerate(values)) / den

    def _trend_velocity(self, history, digit):
        if len(history) >= 40:
            block = 10
            values = history[-40:]
        elif len(history) >= 20:
            block = 5
            values = history[-20:]
        else:
            return 0.0, []

        shares = []
        for i in range(0, len(values), block):
            chunk = values[i:i + block]
            shares.append(sum(1 for d in chunk if d == digit) / len(chunk))
        return float(self._linear_slope(shares)), [float(x) for x in shares]

    @staticmethod
    def _break_digit_target(history):
        if len(history) < 3:
            return None
        a, b, c = history[-3], history[-2], history[-1]
        return int(a) if a == b and c != a else None

    @staticmethod
    def _alternating_pair_targets(history):
        if len(history) < 6:
            return set()
        a, b, c, d, e, breaker = history[-6:]
        if a == c == e and b == d and a != b and breaker not in {a, b}:
            return {int(a), int(b)}
        return set()

    def _dominance_state(self, history):
        window = 100 if len(history) >= 100 else 50 if len(history) >= 50 else 25 if len(history) >= 25 else 10
        freqs = {d: self._freq(history, d, window) for d in range(10)}
        ordered = sorted(freqs.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)
        least = sorted(freqs.items(), key=lambda kv: (kv[1], kv[0]))
        return {
            "window": window,
            "dominant_digit": int(ordered[0][0]),
            "dominant_frequency": float(ordered[0][1]),
            "second_frequency": float(ordered[1][1]),
            "dominance_margin": float(ordered[0][1] - ordered[1][1]),
            "least_frequency_digit": int(least[0][0]),
            "least_frequency": float(least[0][1]),
        }

    def _stable_rows(self, history, exclude_digit=None):
        last10 = history[-10:]
        last25 = history[-25:]

        entropy10_bits = self._entropy(last10)
        entropy25_bits = self._entropy(last25)
        entropy10 = entropy10_bits / math.log2(10)
        entropy25 = entropy25_bits / math.log2(10)

        repeat10 = 0.0
        if len(last10) > 1:
            repeat10 = (
                sum(a == b for a, b in zip(last10[:-1], last10[1:]))
                / (len(last10) - 1)
            )

        current = history[-1]
        rows = []

        for digit in range(10):
            if exclude_digit is not None and digit == int(exclude_digit):
                continue

            f5 = self._freq(history, digit, 5)
            f10 = self._freq(history, digit, 10)
            f25 = self._freq(history, digit, 25)
            f50 = self._freq(history, digit, 50)
            f100 = self._freq(history, digit, 100)
            gap = self._gap(history, digit)
            tr1 = self._transition1(history, digit)
            tr2 = self._transition2(history, digit)
            short_long = f5 - f50
            cluster = f10 - f100

            moderate_gap = max(
                0.0,
                1.0 - abs(min(gap, 16) - 6.0) / 10.0,
            )
            safe_tick_like = 1.0 if (
                f25 <= 0.08
                and entropy10_bits <= 2.5219280948873625
            ) else 0.0

            # ORIGINAL V1 EXECUTION SCORE.
            score = 0.0
            score += 42.0 * (tr1 - 0.10)
            score += 24.0 * (tr2 - 0.10)
            score += 16.0 * (f5 - 0.10)
            score += 12.0 * (f10 - 0.10)
            score += 7.0 * (f25 - 0.10)
            score += 4.0 * (f50 - 0.10)
            score += 2.0 * (f100 - 0.10)
            score += 8.0 * short_long
            score += 5.0 * cluster
            score += 2.0 * moderate_gap
            score += (
                2.0
                * (1.0 if current == digit else 0.0)
                * max(0.0, repeat10 - 0.10)
            )
            score += 1.0 * safe_tick_like
            score *= max(0.55, 1.15 - 0.60 * entropy25)

            rows.append({
                "digit": int(digit),
                "score": float(score),
                "gap": int(gap),
                "freq5": float(f5),
                "freq10": float(f10),
                "freq25": float(f25),
                "freq50": float(f50),
                "freq100": float(f100),
                "entropy10": float(entropy10),
                "entropy25": float(entropy25),
                "repeat10": float(repeat10),
                "transition1": float(tr1),
                "transition2": float(tr2),
                "short_long_divergence": float(short_long),
                "cluster_pressure": float(cluster),
                "safe_tick_like": float(safe_tick_like),
            })

        rows.sort(
            key=lambda r: (
                r["score"],
                r["transition2"],
                r["transition1"],
            ),
            reverse=True,
        )
        return rows

    def _shadow_snapshot(self, history, exclude_digit=None):
        dominance = self._dominance_state(history)
        break_target = self._break_digit_target(history)
        pair_targets = self._alternating_pair_targets(history)

        rows = []
        for digit in range(10):
            if exclude_digit is not None and digit == int(exclude_digit):
                continue

            velocity, blocks = self._trend_velocity(history, digit)
            f10 = self._freq(history, digit, 10)
            tr1 = self._transition1(history, digit)
            tr2 = self._transition2(history, digit)

            dominance_match = digit == dominance["dominant_digit"]
            break_match = break_target is not None and digit == break_target
            pair_match = digit in pair_targets

            signals = {
                "transition1_support": tr1 > 0.11,
                "transition2_support": tr2 > 0.11,
                "trend_velocity_positive": velocity > 0.005,
                "recent_frequency_support": f10 > 0.10,
                "dominant_digit_support": dominance_match and dominance["dominance_margin"] > 0,
                "break_digit_support": break_match,
                "alternating_pair_support": pair_match,
            }
            agreement = sum(bool(v) for v in signals.values())

            # Shadow-only score. Never used for execution.
            shadow_score = (
                6.0 * velocity
                + (min(1.0, 8.0 * dominance["dominance_margin"]) if dominance_match else 0.0)
                + (1.25 if break_match else 0.0)
                + (0.75 if pair_match else 0.0)
                + 0.20 * agreement
            )

            rows.append({
                "digit": int(digit),
                "shadow_score": float(shadow_score),
                "trend_velocity": float(velocity),
                "trend_blocks": blocks,
                "dominance_match": bool(dominance_match),
                "break_digit_match": bool(break_match),
                "alternating_pair_match": bool(pair_match),
                "signals": signals,
                "signal_agreement": int(agreement),
                "signal_total": len(signals),
                "strength": (
                    "STRONG" if agreement >= 5
                    else "MODERATE" if agreement >= 3
                    else "WEAK"
                ),
            })

        rows.sort(
            key=lambda r: (
                r["shadow_score"],
                r["signal_agreement"],
                r["trend_velocity"],
            ),
            reverse=True,
        )

        return {
            "version": self.SHADOW_VERSION,
            "selected_digit": rows[0]["digit"] if rows else None,
            "ranking": rows,
            "dominance": dominance,
            "break_digit_target": break_target,
            "alternating_pair_targets": sorted(pair_targets),
        }

    def rank(self, history, exclude_digit=None):
        history = [
            int(x) for x in history
            if 0 <= int(x) <= 9
        ][-self.max_history:]

        if len(history) < self.min_history:
            return {
                "version": self.VERSION,
                "ready": False,
                "history_count": len(history),
                "minimum_history": self.min_history,
                "selected_digit": None,
                "ranking": [],
                "recycle_after": self.recycle_after,
                "shadow": {
                    "version": self.SHADOW_VERSION,
                    "selected_digit": None,
                    "ranking": [],
                },
            }

        rows = self._stable_rows(history, exclude_digit=exclude_digit)
        top_margin = (
            rows[0]["score"] - rows[1]["score"]
            if len(rows) > 1 else None
        )

        return {
            "version": self.VERSION,
            "ready": bool(rows),
            "history_count": len(history),
            "minimum_history": self.min_history,
            "selected_digit": rows[0]["digit"] if rows else None,
            "ranking": rows,
            "top_margin": float(top_margin) if top_margin is not None else None,
            "excluded_digit": exclude_digit,
            "recycle_after": self.recycle_after,
            "shadow": self._shadow_snapshot(
                history,
                exclude_digit=exclude_digit,
            ),
        }
