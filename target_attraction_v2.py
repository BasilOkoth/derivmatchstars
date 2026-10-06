"""
Target Attraction V2 — Tail Risk Shadow Engine
==============================================

Research-only / shadow-only.

Primary target:
    STOP10 = 1 when the selected target digit does NOT recur within the next
    10 ticks.

Important:
    This module does not place trades.
    It exposes a score and a validation gate only.
    The gate must remain closed unless purged forward validation passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Mapping, Any
import json
import joblib
import numpy as np


FEATURE_NAMES = [
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


@dataclass(frozen=True)
class TailRiskScore:
    stop10_probability: float
    return_by_t10_probability: float
    risk_band: str
    execution_eligible: bool
    reason: str


class TargetAttractionV2Shadow:
    """
    Loads the fitted V2 research model and returns a shadow STOP10 score.

    It NEVER authorizes execution by itself. `execution_eligible` comes only
    from the frozen validation-gate file produced during offline analysis.
    """

    def __init__(
        self,
        model_path: str | Path,
        metrics_path: str | Path,
    ) -> None:
        self.model = joblib.load(model_path)
        self.metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
        self.gate_passed = bool(
            self.metrics.get("execution_gate", {}).get("passed", False)
        )

    @staticmethod
    def _band(p: float) -> str:
        # Descriptive only; not a trade threshold.
        if p < 0.20:
            return "VERY_LOW"
        if p < 0.30:
            return "LOW"
        if p < 0.40:
            return "MODERATE"
        if p < 0.50:
            return "HIGH"
        return "VERY_HIGH"

    def score(self, features: Sequence[float]) -> TailRiskScore:
        x = np.asarray(features, dtype=float).reshape(1, -1)
        if x.shape[1] != len(FEATURE_NAMES):
            raise ValueError(
                f"Expected {len(FEATURE_NAMES)} features, got {x.shape[1]}"
            )

        p_stop10 = float(self.model.predict_proba(x)[0, 1])
        return TailRiskScore(
            stop10_probability=p_stop10,
            return_by_t10_probability=1.0 - p_stop10,
            risk_band=self._band(p_stop10),
            execution_eligible=self.gate_passed,
            reason=(
                "Purged forward validation gate passed."
                if self.gate_passed
                else "Shadow only: purged forward validation gate has not passed."
            ),
        )

    def score_mapping(self, feature_map: Mapping[str, Any]) -> TailRiskScore:
        missing = [k for k in FEATURE_NAMES if k not in feature_map]
        if missing:
            raise KeyError(f"Missing features: {missing}")
        return self.score([feature_map[k] for k in FEATURE_NAMES])
