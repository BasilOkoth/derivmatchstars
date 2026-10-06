#!/usr/bin/env python3
# Apply Target Attraction V2 shadow integration to the CURRENT derivmatchstars repo.
# Run from the repository root:
#     python apply_v2_shadow_integration.py
#
# This patches app/engine.py, app/main.py and bot.html.
# V2 remains SHADOW ONLY and never changes V1 execution decisions.

from pathlib import Path
import ast
import shutil

ROOT = Path.cwd()
ENGINE = ROOT / "app" / "engine.py"
MAIN = ROOT / "app" / "main.py"
BOT = ROOT / "bot.html"

for p in (ENGINE, MAIN, BOT):
    if not p.exists():
        raise SystemExit(f"Missing expected repo file: {p}")

def patch_once(text, old, new, label):
    if new in text:
        print(f"[skip] {label}: already applied")
        return text
    if old not in text:
        raise RuntimeError(f"Patch anchor not found: {label}")
    print(f"[apply] {label}")
    return text.replace(old, new, 1)

for p in (ENGINE, MAIN, BOT):
    backup = p.with_suffix(p.suffix + ".pre-v2-shadow.bak")
    if not backup.exists():
        shutil.copy2(p, backup)

# ---------------- app/engine.py ----------------
e = ENGINE.read_text(encoding="utf-8")

e = patch_once(
    e,
    '''import math
from collections import deque
from datetime import datetime
''',
    '''import math
from collections import deque
from datetime import datetime
from pathlib import Path
''',
    "engine imports",
)

e = patch_once(
    e,
    '''from .deriv_ws import DerivWS


class MultiUserEngine:
''',
    '''from .deriv_ws import DerivWS

try:
    from target_attraction_v2 import TargetAttractionV2Shadow
except Exception:
    TargetAttractionV2Shadow = None


class MultiUserEngine:
''',
    "V2 import",
)

e = patch_once(
    e,
    '''        self.safe_v1_freq25_max = 0.08
        self.safe_v1_entropy10_max = 2.5219280948873625

    async def start(self):
''',
    '''        self.safe_v1_freq25_max = 0.08
        self.safe_v1_entropy10_max = 2.5219280948873625

        # TARGET ATTRACTION V2 — STOP10 TAIL-RISK SHADOW
        # V2 receives the exact same frozen T0 features as V1.
        # It is observational only and cannot arm, block, size, or place trades.
        self.tae_v2_shadow_scores = {}
        self.tae_v2_model = None
        self.tae_v2_load_error = None

        if TargetAttractionV2Shadow is None:
            self.tae_v2_load_error = (
                "TargetAttractionV2Shadow module could not be imported"
            )
        else:
            try:
                root = Path(__file__).resolve().parents[1]
                self.tae_v2_model = TargetAttractionV2Shadow(
                    root / "tail_risk_shadow_v2.joblib",
                    root / "v2_metrics.json",
                )
            except Exception as exc:
                # V2 must never take V1/server execution down with it.
                self.tae_v2_load_error = str(exc)

    async def start(self):
''',
    "V2 loader",
)

e = patch_once(
    e,
    '''    def _tae_predict_from_features(self, sid: int, features):
        model = self._tae_model(sid)
        score = model["bias"]
        for weight, value in zip(model["weights"], features):
            score += weight * value
        return self._sigmoid(score)

    def _tae_train_one(self, sid: int, features, label: int, predicted: float):
''',
    '''    def _tae_predict_from_features(self, sid: int, features):
        model = self._tae_model(sid)
        score = model["bias"]
        for weight, value in zip(model["weights"], features):
            score += weight * value
        return self._sigmoid(score)

    def _tae_v2_score_from_features(self, sid: int, features):
        # Score current T0 context with V2 in shadow-only mode.
        # This has no effect on V1's arm decision or execution flow.
        if self.tae_v2_model is None:
            payload = {
                "available": False,
                "mode": "SHADOW_ONLY",
                "target": "STOP10",
                "stop10_probability": None,
                "return_by_t10_probability": None,
                "risk_band": "UNAVAILABLE",
                "execution_eligible": False,
                "validation_gate_passed": False,
                "error": self.tae_v2_load_error,
            }
            self.tae_v2_shadow_scores[sid] = payload
            return payload

        try:
            score = self.tae_v2_model.score(features)
            metrics = self.tae_v2_model.metrics or {}
            selected_name = metrics.get("selected_shadow_model")
            selected_metrics = (
                (metrics.get("models") or {}).get(selected_name) or {}
            )
            gate = metrics.get("execution_gate") or {}

            payload = {
                "available": True,
                "mode": "SHADOW_ONLY",
                "target": "STOP10",
                "stop10_probability": float(score.stop10_probability),
                "return_by_t10_probability": float(
                    score.return_by_t10_probability
                ),
                "risk_band": str(score.risk_band),
                "execution_eligible": False,
                "validation_gate_passed": bool(gate.get("passed", False)),
                "validation_reason": str(score.reason),
                "selected_shadow_model": selected_name,
                "oof_auc": selected_metrics.get("roc_auc"),
                "mean_forward_auc": selected_metrics.get("mean_fold_auc"),
                "brier_skill_vs_constant": selected_metrics.get(
                    "brier_skill_vs_constant"
                ),
                "note": (
                    "Research-only STOP10 score. V2 does not influence "
                    "trade entry, recovery, stake sizing, or execution."
                ),
            }
            self.tae_v2_shadow_scores[sid] = payload
            return payload
        except Exception as exc:
            payload = {
                "available": False,
                "mode": "SHADOW_ONLY",
                "target": "STOP10",
                "stop10_probability": None,
                "return_by_t10_probability": None,
                "risk_band": "ERROR",
                "execution_eligible": False,
                "validation_gate_passed": False,
                "error": str(exc),
            }
            self.tae_v2_shadow_scores[sid] = payload
            return payload

    def _tae_v2_status(self, sid: int):
        current = self.tae_v2_shadow_scores.get(sid)
        if current is not None:
            return dict(current)

        return {
            "available": self.tae_v2_model is not None,
            "mode": "SHADOW_ONLY",
            "target": "STOP10",
            "stop10_probability": None,
            "return_by_t10_probability": None,
            "risk_band": "WAITING",
            "execution_eligible": False,
            "validation_gate_passed": bool(
                self.tae_v2_model and self.tae_v2_model.gate_passed
            ),
            "error": self.tae_v2_load_error,
            "note": (
                "Waiting for a complete T0 feature vector."
                if self.tae_v2_model is not None
                else "V2 model unavailable; V1 continues independently."
            ),
        }

    def _tae_train_one(self, sid: int, features, label: int, predicted: float):
''',
    "V2 scoring/status methods",
)

e = patch_once(
    e,
    '''        model["last_probability"] = predicted
        model["last_features"] = list(features)
        model["last_target"] = int(target)

        new_sample = {
''',
    '''        model["last_probability"] = predicted
        model["last_features"] = list(features)
        model["last_target"] = int(target)

        # V2 runs beside V1 on the exact same frozen T0 feature vector.
        self._tae_v2_score_from_features(sid, features)

        new_sample = {
''',
    "V2 per-T0 scoring",
)

e = patch_once(
    e,
    '''            "research_stream": dict(self._research_diag_for(sid)),
            "persistent": True,
''',
    '''            "research_stream": dict(self._research_diag_for(sid)),
            "v2_shadow": self._tae_v2_status(sid),
            "persistent": True,
''',
    "Expose V2 in /sessions",
)

ENGINE.write_text(e, encoding="utf-8")
ast.parse(e)
print("[ok] app/engine.py syntax")

# ---------------- app/main.py ----------------
m = MAIN.read_text(encoding="utf-8")
m2 = m.replace("2.2.3-tae-pending-fix", "2.2.4-tae-v2-shadow")
if m2 == m and "2.2.4-tae-v2-shadow" not in m:
    print("[warn] app/main.py version string did not match; leaving version unchanged")
else:
    MAIN.write_text(m2, encoding="utf-8")
    ast.parse(m2)
    print("[ok] app/main.py syntax")

# ---------------- bot.html ----------------
b = BOT.read_text(encoding="utf-8")

b = patch_once(
    b,
    '<div id="tae-live-mode" class="text-[10px] font-bold text-cyan-300">PERSISTENT · FORWARD-ONLY</div>',
    '<div id="tae-live-mode" class="text-[10px] font-bold text-cyan-300">V1 ENTRY · V2 SHADOW</div>',
    "Dashboard V2 mode badge",
)

b = patch_once(
    b,
    '''                                <span class="text-gray-400">Current P(return ≤ T10):</span>
                                <span id="tae-live-prob" class="font-bold text-yellow-300">—</span>

                                <span class="text-gray-400">Model state:</span>
''',
    '''                                <span class="text-gray-400">V1 P(return ≤ T10):</span>
                                <span id="tae-live-prob" class="font-bold text-yellow-300">—</span>

                                <span class="text-gray-400">V2 P(STOP10):</span>
                                <span id="tae-v2-stop10-risk" class="font-black text-orange-300">—</span>

                                <span class="text-gray-400">V2 risk band:</span>
                                <span id="tae-v2-risk-band" class="font-bold text-white">WAITING</span>

                                <span class="text-gray-400">V2 validation gate:</span>
                                <span id="tae-v2-gate" class="font-black text-rose-300">FAILED</span>

                                <span class="text-gray-400">V2 mode:</span>
                                <span id="tae-v2-mode" class="font-bold text-cyan-300">SHADOW ONLY</span>

                                <span class="text-gray-400">Model state:</span>
''',
    "Dashboard V2 rows",
)

b = patch_once(
    b,
    '''            setText('tae-live-stop10', pct(tae.selected_stop10_rate));
            setText('tae-live-prob', pct(tae.current_probability_t10));

            let state = 'WARMING';
''',
    '''            setText('tae-live-stop10', pct(tae.selected_stop10_rate));
            setText('tae-live-prob', pct(tae.current_probability_t10));

            const v2 = tae.v2_shadow || {};
            setText(
                'tae-v2-stop10-risk',
                v2.available ? pct(v2.stop10_probability) : '—'
            );
            setText(
                'tae-v2-risk-band',
                v2.risk_band || (v2.available ? 'WAITING' : 'UNAVAILABLE')
            );
            setText(
                'tae-v2-gate',
                v2.validation_gate_passed ? 'PASSED' : 'FAILED'
            );
            setText(
                'tae-v2-mode',
                String(v2.mode || 'SHADOW_ONLY').replaceAll('_', ' ')
            );

            const v2RiskEl = document.getElementById('tae-v2-stop10-risk');
            if (v2RiskEl) {
                const risk = Number(v2.stop10_probability);
                v2RiskEl.className = Number.isFinite(risk)
                    ? (
                        risk < 0.30
                            ? 'font-black text-emerald-300'
                            : risk < 0.40
                                ? 'font-black text-yellow-300'
                                : 'font-black text-orange-300'
                    )
                    : 'font-black text-gray-400';
            }

            const v2GateEl = document.getElementById('tae-v2-gate');
            if (v2GateEl) {
                v2GateEl.className = v2.validation_gate_passed
                    ? 'font-black text-emerald-300'
                    : 'font-black text-rose-300';
            }

            let state = 'WARMING';
''',
    "Render V2 shadow metrics",
)

BOT.write_text(b, encoding="utf-8")
print("[ok] bot.html patched")

required = [
    "target_attraction_v2.py",
    "tail_risk_shadow_v2.joblib",
    "v2_metrics.json",
]
missing = [name for name in required if not (ROOT / name).exists()]
if missing:
    print("[warn] Missing V2 root assets:", ", ".join(missing))
    print("       Copy them from this integration bundle to repo root before deploy.")
else:
    print("[ok] V2 model assets present")

print("\nDONE.")
print("V1 remains the execution/entry engine.")
print("V2 is exposed at /sessions -> tae -> v2_shadow.")
print("V2 remains SHADOW ONLY and cannot authorize a trade.")
