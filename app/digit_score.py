from __future__ import annotations

import math
from collections import Counter


class DigitScoreEngine:
    """Rank digits 0-9 from already-observed canonical tick history.

    The score is a relative ranking signal, not a guaranteed win probability.
    It combines the feature families already studied in DigitMatchStar while
    deliberately preventing a large gap from becoming an endless 'overdue'
    chase signal.
    """

    def __init__(self, recycle_after: int = 3, min_history: int = 10, max_history: int = 100):
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

    def rank(self, history, exclude_digit=None):
        history = [int(x) for x in history if 0 <= int(x) <= 9][-self.max_history:]
        if len(history) < self.min_history:
            return {
                "ready": False,
                "history_count": len(history),
                "minimum_history": self.min_history,
                "selected_digit": None,
                "ranking": [],
                "recycle_after": self.recycle_after,
            }

        last10 = history[-10:]
        last25 = history[-25:]
        entropy10_bits = self._entropy(last10)
        entropy25_bits = self._entropy(last25)
        entropy10 = entropy10_bits / math.log2(10)
        entropy25 = entropy25_bits / math.log2(10)

        repeat10 = 0.0
        if len(last10) > 1:
            repeat10 = sum(a == b for a, b in zip(last10[:-1], last10[1:])) / (len(last10) - 1)

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

            # Avoid the gambler's-fallacy failure mode discovered in the TAE
            # work: reward a moderate gap, not an ever-growing gap.
            moderate_gap = max(0.0, 1.0 - abs(min(gap, 16) - 6.0) / 10.0)
            safe_tick_like = 1.0 if (f25 <= 0.08 and entropy10_bits <= 2.5219280948873625) else 0.0

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
            score += 2.0 * (1.0 if current == digit else 0.0) * max(0.0, repeat10 - 0.10)
            score += 1.0 * safe_tick_like

            # High entropy compresses confidence rather than creating fake edge.
            score *= max(0.55, 1.15 - 0.60 * entropy25)

            rows.append({
                "digit": digit,
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

        rows.sort(key=lambda r: (r["score"], r["transition2"], r["transition1"]), reverse=True)
        return {
            "ready": bool(rows),
            "history_count": len(history),
            "minimum_history": self.min_history,
            "selected_digit": rows[0]["digit"] if rows else None,
            "ranking": rows,
            "top_margin": (rows[0]["score"] - rows[1]["score"]) if len(rows) > 1 else None,
            "excluded_digit": exclude_digit,
            "recycle_after": self.recycle_after,
        }
