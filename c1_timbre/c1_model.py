"""C1 baseline predictor: one ridge regression per descriptor on c1_features_v2.

    predicted score = intercept + sum_k weight_k * (feature_k - train_mean_k) / train_sd_k

Scaling statistics and the ridge penalty come from training sounds only. The
model is saved as plain JSON so it can be inspected and reloaded without pickle.
Raw predictions can leave 1-7; `clip_scores` is the explicit display rule.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ALPHAS = np.logspace(-3, 3, 25)
SCALE = (1.0, 7.0)


class RidgeModel:
    def fit(self, X: np.ndarray, y: np.ndarray, alpha: float):
        self.mean, self.sd = X.mean(0), X.std(0)
        self.sd[self.sd < 1e-12] = 1.0
        Z = (X - self.mean) / self.sd
        self.intercept = float(y.mean())
        self.alpha = float(alpha)
        self.coef = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - self.intercept))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.intercept + ((X - self.mean) / self.sd) @ self.coef

    def to_dict(self, features):
        return dict(features=list(features), alpha=self.alpha, intercept=self.intercept,
                    train_mean=self.mean.tolist(), train_sd=self.sd.tolist(), weights=self.coef.tolist())

    @classmethod
    def from_dict(cls, d):
        m = cls()
        m.alpha, m.intercept = d["alpha"], d["intercept"]
        m.mean, m.sd, m.coef = (np.array(d[k]) for k in ("train_mean", "train_sd", "weights"))
        return m


def kfold(n: int, k: int, rng) -> list[np.ndarray]:
    order = rng.permutation(n)
    return [order[i::k] for i in range(k)]


def select_alpha(X, y, rng, k=5, alphas=ALPHAS):
    """Choose the penalty by k-fold CV over training sounds only."""
    folds = kfold(len(y), min(k, len(y)), rng)
    errors = []
    for a in alphas:
        sse = 0.0
        for test in folds:
            train = np.setdiff1d(np.arange(len(y)), test)
            sse += np.sum((y[test] - RidgeModel().fit(X[train], y[train], a).predict(X[test])) ** 2)
        errors.append(sse / len(y))
    best = int(np.argmin(errors))
    return float(alphas[best]), dict(zip(map(float, alphas), map(float, errors)))


def fit_with_selection(X, y, rng):
    alpha, curve = select_alpha(X, y, rng)
    return RidgeModel().fit(X, y, alpha), curve


def clip_scores(pred):
    return np.clip(pred, *SCALE)


def safe_spearman(a, b):
    if len(a) < 3 or np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return None  # undefined for constant input
    return float(spearmanr(a, b)[0])


def metrics(y, pred, baseline):
    """Score-unit errors, ranking agreement and improvement over a train-mean predictor."""
    sst = np.sum((y - baseline) ** 2)
    return dict(n=int(len(y)), mae=float(np.mean(np.abs(y - pred))), rmse=float(np.sqrt(np.mean((y - pred) ** 2))),
                baseline_mae=float(np.mean(np.abs(y - baseline))),
                r2_vs_train_mean=float(1 - np.sum((y - pred) ** 2) / sst) if sst > 0 else None,
                spearman=safe_spearman(y, pred), outside_1_7=int(np.sum((pred < SCALE[0]) | (pred > SCALE[1]))),
                prediction_sd=float(np.std(pred)), target_sd=float(np.std(y)))


def save_models(path: Path, models: dict, features, provenance: dict):
    path.write_text(json.dumps(dict(provenance=provenance, display_rule="clip to [1, 7]",
                                    descriptors={t: m.to_dict(features) for t, m in models.items()}), indent=2),
                    encoding="utf-8")


def load_models(path: Path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {t: RidgeModel.from_dict(m) for t, m in d["descriptors"].items()}, d
