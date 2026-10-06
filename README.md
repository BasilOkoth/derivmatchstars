# Target Attraction V2 — Tail Risk Shadow

This package converts the V1 research objective from **predict return by T10**
to the failure event that matters directly:

> **STOP10 = target digit does not recur within the next 10 ticks.**

## What was tested

Source export: `target-attraction-v1-R_10-2026-10-06T15-41-15-834Z.json`

Eligible matured observations after V1's 250-sample warm-up: **2,582**

Observed STOP10 rate: **35.86%**

Validation:
- forward-only
- 5 expanding folds
- 300 observations per validation fold
- 10-tick purge gap between train and validation
- two candidate models:
  - L2 penalized logistic regression
  - shallow histogram gradient boosting

## Result

Selected shadow model: **shallow_hgb**

Mean fold AUC: **0.450**

OOF AUC: **0.441**

PR-AUC: **0.365**

Brier score: **0.2614**

Constant-rate baseline Brier: **0.2375**

Brier skill vs constant: **-0.101**

Execution gate passed: **False**

## Meaning

The V2 architecture is implemented, but the current 12-feature dataset does
**not** pass the forward-validation gate. Therefore V2 must remain **shadow-only**.

Do not lower a threshold to force entries. The current features do not yet
show stable forward discrimination of STOP10.

## Files

- `target_attraction_v2.py` — shadow scorer
- `tail_risk_shadow_v2.joblib` — fitted research model
- `v2_metrics.json` — frozen validation result and gate
- `purged_forward_cv.csv` — fold-by-fold metrics
- `evaluate_v2.py` — reproducible evaluator

## Integration contract

Feed the exact 12 T0 features in the same order as V1. The scorer returns:

- `stop10_probability`
- `return_by_t10_probability`
- `risk_band`
- `execution_eligible`
- `reason`

At this stage `execution_eligible` is intentionally `False`.
