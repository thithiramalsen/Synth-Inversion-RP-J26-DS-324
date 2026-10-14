"""Pluggable relevance functions (higher = more relevant to the target).

Selection code only ever sees the relevance vector these return, so swapping MFCC for a
learned C4 metric needs no change in ``selection.py`` (guide §8.4).

Audio implementations (``MFCC26Relevance``, ``LogMelStatsRelevance``, optional CLAP) are
added in Phase 6.
"""

from __future__ import annotations

from typing import Protocol, Sequence

import numpy as np
import pandas as pd

from .param_space import ParamDistance


class RelevanceFunction(Protocol):
    name: str

    def fit(self, bank_ids: Sequence[str]) -> None:
        """Prepare using bank samples only (e.g. feature standardisation statistics)."""

    def score_bank(self, target_id: str) -> np.ndarray:
        """Relevance of every fitted bank sample to a target, in ``fit`` order (fast path)."""

    def score_ids(self, target_id: str, candidate_ids: Sequence[str]) -> np.ndarray:
        """Relevance of each candidate to an in-dataset target."""

    def score_audio(self, audio: np.ndarray, sr: int, candidate_ids: Sequence[str]) -> np.ndarray:
        """Relevance of each candidate to an external audio query."""


class ParamProxyRelevance:
    """SMOKE TEST ONLY — not an audio relevance measure, never used for reported results.

    ``relevance(t, c) = 1 - euclid_sqrt_d(t, c)`` over a seeded subset of parameters, plus
    Gaussian noise (sigma 0.01). Correlated with, but not identical to, the diversity space,
    so the MMR trade-off can be exercised before audio exists (Phase 4).

    Noise is a deterministic function of (seed, target, candidate), so scores do not depend
    on candidate order or on which other candidates are scored.
    """

    name = "SMOKE_TEST_PROXY"

    def __init__(self, unit_params: pd.DataFrame, seed: int, subset_fraction: float = 0.5,
                 noise_sigma: float = 0.01):
        self.unit_params = unit_params
        self.seed = int(seed)
        self.noise_sigma = float(noise_sigma)
        n_dims = unit_params.shape[1]
        n_subset = max(1, int(round(n_dims * subset_fraction)))
        chosen = np.random.default_rng(self.seed).choice(n_dims, size=n_subset, replace=False)
        self.subset_columns = [unit_params.columns[i] for i in sorted(chosen)]
        self._values = unit_params[self.subset_columns].to_numpy(dtype=np.float64)
        self._position = pd.Series(np.arange(len(unit_params)), index=unit_params.index)
        self._metric = ParamDistance(len(self.subset_columns), method="euclid_sqrt_d")
        self.bank_ids: list[str] | None = None

    def describe(self) -> dict:
        return {"relevance": self.name, "subset_columns": self.subset_columns,
                "noise_sigma": self.noise_sigma, "seed": self.seed}

    def fit(self, bank_ids: Sequence[str]) -> None:
        self.bank_ids = list(bank_ids)
        self._bank_pos = self._position.loc[self.bank_ids].to_numpy()

    def _score_positions(self, target_id: str, cand_pos: np.ndarray) -> np.ndarray:
        target_pos = int(self._position[target_id])
        base = 1.0 - self._metric.cdist(self._values[target_pos], self._values[cand_pos])[0]
        noise = np.random.default_rng([self.seed, target_pos]).normal(0.0, self.noise_sigma, len(self._position))
        return base + noise[cand_pos]

    def score_bank(self, target_id: str) -> np.ndarray:
        if self.bank_ids is None:
            raise RuntimeError("call fit(bank_ids) before score_bank")
        return self._score_positions(target_id, self._bank_pos)

    def score_ids(self, target_id: str, candidate_ids: Sequence[str]) -> np.ndarray:
        return self._score_positions(target_id, self._position.loc[list(candidate_ids)].to_numpy())

    def score_audio(self, audio: np.ndarray, sr: int, candidate_ids: Sequence[str]) -> np.ndarray:
        raise NotImplementedError("ParamProxyRelevance is a smoke-test proxy and cannot score audio")


class C4Relevance:
    """Placeholder for teammate C4's human-aligned similarity model.

    Expected interface once C4 delivers a model:

    * ``fit(bank_ids)`` - load/cache C4 embeddings for bank sounds (no val/test statistics).
    * ``score_ids(target_id, candidate_ids)`` - C4 similarity between the target sound and
      each candidate, higher = more similar, one float per candidate in the given order.
    * ``score_audio(audio, sr, candidate_ids)`` - same for an external mono clip; C4 is
      responsible for its own resampling/feature extraction.

    Scores need not lie in [0, 1], but their scale matters for MMR (guide §8.3).
    """

    name = "c4"

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("C4 relevance is not available yet; waiting for the C4 model")

    def fit(self, bank_ids):  # pragma: no cover - unreachable until implemented
        raise NotImplementedError

    def score_bank(self, target_id):  # pragma: no cover
        raise NotImplementedError

    def score_ids(self, target_id, candidate_ids):  # pragma: no cover
        raise NotImplementedError

    def score_audio(self, audio, sr, candidate_ids):  # pragma: no cover
        raise NotImplementedError


class FeatureCosineRelevance:
    """Audio relevance: cosine similarity of bank-standardised feature summaries (Phase 6).

    ``fit`` z-scores every feature with the mean/std of the BANK rows only (no val/test
    statistics), then L2-normalises each row; relevance is the dot product. Dimensions with
    zero bank variance are left unscaled (std set to 1) and reported in ``describe()``.
    ``score_audio`` expects audio already prepared like the corpus
    (:func:`c3.audio_io.load_external_audio`).
    """

    def __init__(self, representation: str, features: np.ndarray, sample_ids: Sequence[str], extractor=None):
        self.name = representation
        self.representation = representation
        self._features = np.asarray(features, dtype=np.float64)
        if self._features.ndim != 2 or len(self._features) != len(sample_ids):
            raise ValueError("features must be a 2-D array with one row per sample ID")
        if not np.isfinite(self._features).all():
            raise ValueError("features contain non-finite values")
        self._position = pd.Series(np.arange(len(sample_ids)), index=pd.Index(sample_ids))
        self.extractor = extractor
        self.bank_ids: list[str] | None = None

    @classmethod
    def from_cache(cls, features_dir, representation: str) -> "FeatureCosineRelevance":
        from .features import FeatureExtractor, FeatureSettings, load_feature_cache

        array, ids, meta = load_feature_cache(features_dir, representation)
        settings = FeatureSettings(**meta["settings"])
        return cls(representation, array, ids, extractor=FeatureExtractor(settings))

    def fit(self, bank_ids: Sequence[str]) -> None:
        self.bank_ids = list(bank_ids)
        bank_pos = self._position.loc[self.bank_ids].to_numpy()
        bank = self._features[bank_pos]
        self.mean = bank.mean(axis=0)
        std = bank.std(axis=0)
        self.zero_variance_dims = np.flatnonzero(std == 0).tolist()
        self.std = np.where(std == 0, 1.0, std)
        self._unit_all = self._normalise((self._features - self.mean) / self.std)
        self._bank_matrix = np.ascontiguousarray(self._unit_all[bank_pos])

    @staticmethod
    def _normalise(z: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(z, axis=-1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("a standardised feature vector is exactly zero; cosine is undefined")
        return z / norms

    def _require_fit(self):
        if self.bank_ids is None:
            raise RuntimeError("call fit(bank_ids) first")

    def score_bank(self, target_id: str) -> np.ndarray:
        self._require_fit()
        return self._bank_matrix @ self._unit_all[int(self._position[target_id])]

    def score_ids(self, target_id: str, candidate_ids: Sequence[str]) -> np.ndarray:
        self._require_fit()
        candidates = self._unit_all[self._position.loc[list(candidate_ids)].to_numpy()]
        return candidates @ self._unit_all[int(self._position[target_id])]

    def score_audio(self, audio: np.ndarray, sr: int, candidate_ids: Sequence[str]) -> np.ndarray:
        self._require_fit()
        if self.extractor is None:
            raise RuntimeError("no feature extractor attached; build with from_cache or pass extractor=")
        vector = self.extractor.extract(audio, sr)[self.representation]
        query = self._normalise((vector - self.mean) / self.std)
        return self._unit_all[self._position.loc[list(candidate_ids)].to_numpy()] @ query

    def describe(self) -> dict:
        return {"relevance": self.representation, "similarity": "cosine",
                "standardize_with": "bank", "n_bank": None if self.bank_ids is None else len(self.bank_ids),
                "zero_variance_dims": getattr(self, "zero_variance_dims", None)}
