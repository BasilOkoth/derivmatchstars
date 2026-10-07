from __future__ import annotations

import math
from collections import Counter


class DigitScoreEngine:
    """
    DigitScore V2 — Trigger Fusion.

    Ranks digits 0-9 from already-observed canonical tick history.

    IMPORTANT:
    - Scores are relative ranking signals, not calibrated probabilities.
    - No hard entry threshold is used.
    - Long-window features mature gradually instead of pretending that a
      10-tick history is already a full 50/100-tick sample.
    - Internet/manual trading patterns are treated as candidate signals only.
    """

    VERSION = "DIGIT_SCORE_V2_TRIGGER_FUSION"

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
        return (
            sum(1 for d in values if d == digit) / len(values)
            if values else 0.0
        )

    @staticmethod
    def _maturity(history_len, window):
        return max(0.0, min(1.0, float(history_len) / float(window)))

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
        # Smoothed toward the 10% neutral baseline.
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
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den else 0.0

    def _trend_velocity(self, history, digit):
        """
        Real rolling frequency velocity.

        Prefer four non-overlapping 10-tick blocks over 40 ticks. During warm-up,
        use four 5-tick blocks over 20 ticks. Positive slope means the digit's
        local share has been increasing from older -> newer blocks.
        """
        n = len(history)
        if n >= 40:
            block = 10
            values = history[-40:]
        elif n >= 20:
            block = 5
            values = history[-20:]
        else:
            # Too little history for a meaningful multi-block trend.
            return 0.0, []

        shares = []
        for i in range(0, len(values), block):
            chunk = values[i:i + block]
            if chunk:
                shares.append(sum(1 for d in chunk if d == digit) / len(chunk))

        slope = self._linear_slope(shares)
        return float(slope), [float(x) for x in shares]

    @staticmethod
    def _break_digit_target(history):
        """
        Detect strict AA-BREAK:
            ..., A, A, B   where B != A
        Candidate target is A.
        """
        if len(history) < 3:
            return None
        a, b, c = history[-3], history[-2], history[-1]
        if a == b and c != a:
            return int(a)
        return None

    @staticmethod
    def _alternating_pair_targets(history):
        """
        Detect strict alternating pair then break:
            A, B, A, B, A, C
        where C is not A or B.
        Returns {A, B}. This is evidence only, never an automatic entry.
        """
        if len(history) < 6:
            return set()

        a, b, c, d, e, breaker = history[-6:]
        if (
            a == c == e
            and b == d
            and a != b
            and breaker not in {a, b}
        ):
            return {int(a), int(b)}
        return set()

    def _dominance_state(self, history):
        """
        Determine dominant/least digit using the longest reasonably mature
        frequency window available.
        """
        n = len(history)
        if n >= 100:
            window = 100
        elif n >= 50:
            window = 50
        elif n >= 25:
            window = 25
        else:
            window = 10

        freqs = {
            d: self._freq(history, d, window)
            for d in range(10)
        }
        ordered = sorted(freqs.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)
        dominant_digit, dominant_freq = ordered[0]
        second_freq = ordered[1][1] if len(ordered) > 1 else dominant_freq

        least_ordered = sorted(freqs.items(), key=lambda kv: (kv[1], kv[0]))
        least_digit, least_freq = least_ordered[0]

        return {
            "window": int(window),
            "dominant_digit": int(dominant_digit),
            "dominant_frequency": float(dominant_freq),
            "second_frequency": float(second_freq),
            "dominance_margin": float(dominant_freq - second_freq),
            "least_frequency_digit": int(least_digit),
            "least_frequency": float(least_freq),
            "frequencies": freqs,
        }

    @staticmethod
    def _strength_label(agreement):
        if agreement >= 5:
            return "STRONG"
        if agreement >= 3:
            return "MODERATE"
        return "WEAK"

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
            }

        n = len(history)
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
        break_target = self._break_digit_target(history)
        alternating_targets = self._alternating_pair_targets(history)
        dominance = self._dominance_state(history)

        maturity25 = self._maturity(n, 25)
        maturity50 = self._maturity(n, 50)
        maturity100 = self._maturity(n, 100)

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

            # Avoid gambler's-fallacy chasing: reward a moderate gap, not an
            # endlessly increasing one.
            moderate_gap = max(
                0.0,
                1.0 - abs(min(gap, 16) - 6.0) / 10.0,
            )

            safe_tick_like = 1.0 if (
                f25 <= 0.08
                and entropy10_bits <= 2.5219280948873625
            ) else 0.0

            # ---------------- Base score: preserve V1 logic ----------------
            base_score = 0.0
            base_score += 42.0 * (tr1 - 0.10)
            base_score += 24.0 * (tr2 - 0.10)
            base_score += 16.0 * (f5 - 0.10)
            base_score += 12.0 * (f10 - 0.10)

            # Long windows now mature gradually.
            base_score += 7.0 * maturity25 * (f25 - 0.10)
            base_score += 4.0 * maturity50 * (f50 - 0.10)
            base_score += 2.0 * maturity100 * (f100 - 0.10)

            base_score += 8.0 * short_long
            base_score += 5.0 * cluster
            base_score += 2.0 * moderate_gap
            base_score += (
                2.0
                * (1.0 if current == digit else 0.0)
                * max(0.0, repeat10 - 0.10)
            )
            base_score += 1.0 * safe_tick_like

            # High entropy compresses confidence, same philosophy as V1.
            entropy_multiplier = max(
                0.55,
                1.15 - 0.60 * entropy25,
            )
            base_score *= entropy_multiplier

            # ---------------- Trigger Fusion additions ----------------
            trend_velocity, trend_blocks = self._trend_velocity(history, digit)

            # Keep velocity meaningful but bounded. A 10 percentage-point rise
            # per block contributes +0.60 to score.
            trend_bonus = max(-1.20, min(1.20, 6.0 * trend_velocity))

            dominance_margin = dominance["dominance_margin"]
            dominance_match = digit == dominance["dominant_digit"]
            dominance_bonus = (
                min(1.00, 8.0 * dominance_margin)
                if dominance_match else 0.0
            )

            break_match = break_target is not None and digit == break_target
            break_bonus = 1.25 if break_match else 0.0

            alternating_match = digit in alternating_targets
            alternating_bonus = 0.75 if alternating_match else 0.0

            # Research-only Digit 9 setup. It is deliberately NOT given a
            # special execution bonus until forward evidence supports it.
            digit9_setup = bool(
                digit == 9
                and dominance["dominant_digit"] % 2 == 0
                and dominance["least_frequency_digit"] == 0
                and trend_velocity > 0
                and current == 9
            )

            # Count independent evidence families. This is displayed and logged;
            # it is NOT a hard trade threshold.
            signals = {
                "transition1_support": tr1 > 0.11,
                "transition2_support": tr2 > 0.11,
                "trend_velocity_positive": trend_velocity > 0.005,
                "recent_frequency_support": f10 > 0.10,
                "dominant_digit_support": bool(
                    dominance_match and dominance_margin > 0
                ),
                "break_digit_support": break_match,
                "alternating_pair_support": alternating_match,
            }
            agreement = sum(bool(v) for v in signals.values())
            strength = self._strength_label(agreement)

            trigger_bonus = (
                trend_bonus
                + dominance_bonus
                + break_bonus
                + alternating_bonus
            )

            final_score = base_score + trigger_bonus

            rows.append({
                "digit": int(digit),
                "score": float(final_score),
                "base_score": float(base_score),
                "trigger_bonus": float(trigger_bonus),

                "gap": int(gap),
                "freq5": float(f5),
                "freq10": float(f10),
                "freq25": float(f25),
                "freq50": float(f50),
                "freq100": float(f100),

                "freq25_maturity": float(maturity25),
                "freq50_maturity": float(maturity50),
                "freq100_maturity": float(maturity100),

                "entropy10": float(entropy10),
                "entropy25": float(entropy25),
                "repeat10": float(repeat10),

                "transition1": float(tr1),
                "transition2": float(tr2),
                "short_long_divergence": float(short_long),
                "cluster_pressure": float(cluster),
                "safe_tick_like": float(safe_tick_like),

                "trend_velocity": float(trend_velocity),
                "trend_blocks": trend_blocks,
                "trend_bonus": float(trend_bonus),

                "dominance_match": bool(dominance_match),
                "dominance_bonus": float(dominance_bonus),
                "dominance_window": int(dominance["window"]),
                "dominance_margin": float(dominance_margin),

                "break_digit_match": bool(break_match),
                "break_digit_bonus": float(break_bonus),
                "alternating_pair_match": bool(alternating_match),
                "alternating_pair_bonus": float(alternating_bonus),

                "digit9_setup": bool(digit9_setup),

                "signals": signals,
                "signal_agreement": int(agreement),
                "signal_total": int(len(signals)),
                "strength": strength,
            })

        rows.sort(
            key=lambda r: (
                r["score"],
                r["signal_agreement"],
                r["trend_velocity"],
                r["transition2"],
                r["transition1"],
            ),
            reverse=True,
        )

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

            "dominance": {
                "window": dominance["window"],
                "dominant_digit": dominance["dominant_digit"],
                "dominant_frequency": dominance["dominant_frequency"],
                "second_frequency": dominance["second_frequency"],
                "dominance_margin": dominance["dominance_margin"],
                "least_frequency_digit": dominance["least_frequency_digit"],
                "least_frequency": dominance["least_frequency"],
            },
            "break_digit_target": break_target,
            "alternating_pair_targets": sorted(alternating_targets),
            "current_digit": int(current),
        }
