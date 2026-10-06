#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

def models():
    return {
        "penalized_logistic": Pipeline([
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=0.25, solver="lbfgs", max_iter=2000)),
        ]),
        "shallow_hgb": HistGradientBoostingClassifier(
            max_depth=2,
            learning_rate=0.05,
            max_iter=120,
            min_samples_leaf=40,
            l2_regularization=2.0,
            random_state=42,
        ),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_json")
    args = ap.parse_args()

    data = json.loads(Path(args.export_json).read_text(encoding="utf-8"))
    df = pd.DataFrame(data["records"])
    X = np.vstack(df["features"].to_numpy())
    y = df["stop10"].astype(int).to_numpy()
    ready = df["model_trained_samples_at_t0"].astype(int).to_numpy() >= 250
    X, y = X[ready], y[ready]

    splitter = TimeSeriesSplit(n_splits=5, test_size=300, gap=10)

    for name, template in models().items():
        probs = np.full(len(y), np.nan)
        fold_aucs = []
        for tr, va in splitter.split(X):
            model = models()[name]
            model.fit(X[tr], y[tr])
            p = model.predict_proba(X[va])[:, 1]
            probs[va] = p
            fold_aucs.append(roc_auc_score(y[va], p))

        keep = ~np.isnan(probs)
        p = probs[keep]
        yy = y[keep]
        base = np.full(len(yy), yy.mean())
        brier = brier_score_loss(yy, p)
        base_brier = brier_score_loss(yy, base)

        print(json.dumps({
            "model": name,
            "mean_forward_auc": float(np.mean(fold_aucs)),
            "oof_auc": float(roc_auc_score(yy, p)),
            "oof_pr_auc": float(average_precision_score(yy, p)),
            "brier": float(brier),
            "baseline_brier": float(base_brier),
            "brier_skill": float(1 - brier / base_brier),
            "n": int(len(yy)),
        }, indent=2))

if __name__ == "__main__":
    main()
