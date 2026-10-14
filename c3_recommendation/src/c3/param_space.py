"""Distances in editable parameter space (unit-scaled slider positions).

* ``euclid_sqrt_d`` - ``||a - b||_2 / sqrt(sum(w))`` (``sqrt(d)`` for equal weights), the
  legacy prototype's metric. Range [0, 1] on unit vectors.
* ``gower``         - weighted mean of per-dimension distances: ``|a - b|`` for continuous,
  ``0/1`` mismatch for categorical. Range [0, 1].

``scipy.spatial.distance.cdist`` is used rather than the dot-product expansion so that
identical vectors give exactly 0 (needed by the exact-duplicate guard).
"""

from __future__ import annotations

from typing import Iterator, Sequence

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist, pdist

from .schema import ParamSchema

EUCLID = "euclid_sqrt_d"
GOWER = "gower"
DEFAULT_MAX_CELLS = 1 << 24  # ~16.7M distances (~134 MB float64) per block


def to_unit(vital: pd.DataFrame, schema: ParamSchema) -> pd.DataFrame:
    """Vital normalized values -> unit scale using the verified min/max rule."""
    return schema.to_unit(vital)


def resolve_method(method: str, schema: ParamSchema | None = None, categorical_mask=None) -> str:
    if method in (EUCLID, GOWER):
        if method == EUCLID and _has_categorical(schema, categorical_mask):
            raise ValueError("euclid_sqrt_d is only defined for all-continuous parameters; use gower")
        return method
    if method != "auto":
        raise ValueError(f"unknown distance method {method!r}")
    return GOWER if _has_categorical(schema, categorical_mask) else EUCLID


def _has_categorical(schema: ParamSchema | None, categorical_mask) -> bool:
    if categorical_mask is not None:
        return bool(np.asarray(categorical_mask, dtype=bool).any())
    return schema is not None and not schema.all_continuous


def _as_matrix(values) -> np.ndarray:
    array = values.to_numpy(dtype=np.float64) if isinstance(values, pd.DataFrame) else np.asarray(values, np.float64)
    if array.ndim == 1:
        array = array[None, :]
    if array.ndim != 2:
        raise ValueError("parameter arrays must be 1-D or 2-D")
    return array


class ParamDistance:
    """Configured parameter-space metric; all inputs are unit-scaled vectors."""

    def __init__(
        self,
        n_dims: int,
        method: str = "auto",
        categorical_mask: Sequence[bool] | None = None,
        weights: Sequence[float] | None = None,
    ):
        self.n_dims = int(n_dims)
        self.categorical_mask = (
            np.zeros(self.n_dims, dtype=bool) if categorical_mask is None else np.asarray(categorical_mask, bool)
        )
        if self.categorical_mask.shape != (self.n_dims,):
            raise ValueError("categorical_mask length must equal n_dims")
        self.weights = np.ones(self.n_dims) if weights is None else np.asarray(weights, dtype=np.float64)
        if self.weights.shape != (self.n_dims,) or (self.weights < 0).any() or self.weights.sum() <= 0:
            raise ValueError("weights must be non-negative, length n_dims, with a positive sum")
        self.method = resolve_method(method, categorical_mask=self.categorical_mask)

    @classmethod
    def from_schema(cls, schema: ParamSchema, method: str = "auto", weights=None) -> "ParamDistance":
        return cls(len(schema), method=method, categorical_mask=schema.categorical_mask, weights=weights)

    def describe(self) -> dict:
        return {
            "method": self.method,
            "n_dims": self.n_dims,
            "weights": None if np.all(self.weights == 1) else self.weights.tolist(),
            "categorical_dims": int(self.categorical_mask.sum()),
        }

    # ------------------------------------------------------------------ core metric
    def _check(self, array: np.ndarray) -> np.ndarray:
        if array.shape[1] != self.n_dims:
            raise ValueError(f"expected {self.n_dims} parameter columns, got {array.shape[1]}")
        return array

    def cdist(self, A, B) -> np.ndarray:
        """Distance matrix of shape ``(len(A), len(B))``."""
        a, b = self._check(_as_matrix(A)), self._check(_as_matrix(B))
        if self.method == EUCLID:
            out = cdist(a, b, "euclidean", w=self.weights) / np.sqrt(self.weights.sum())
        else:
            cont, cat = ~self.categorical_mask, self.categorical_mask
            total = np.zeros((a.shape[0], b.shape[0]))
            if cont.any():
                total += cdist(a[:, cont], b[:, cont], "cityblock", w=self.weights[cont])
            if cat.any():
                total += cdist(a[:, cat], b[:, cat], "hamming", w=self.weights[cat]) * self.weights[cat].sum()
            out = total / self.weights.sum()
        return np.clip(out, 0.0, 1.0)

    def pdist(self, X) -> np.ndarray:
        """Condensed pairwise distances within ``X`` (``k(k-1)/2`` values)."""
        x = self._check(_as_matrix(X))
        if len(x) < 2:
            return np.empty(0)
        rows, cols = np.triu_indices(len(x), k=1)
        if self.method == EUCLID:
            out = pdist(x, "euclidean", w=self.weights) / np.sqrt(self.weights.sum())
            return np.clip(out, 0.0, 1.0)
        return self.cdist(x, x)[rows, cols]

    def iter_cdist(self, A, B, max_cells: int = DEFAULT_MAX_CELLS) -> Iterator[tuple[int, np.ndarray]]:
        """Yield ``(row_start, block)`` over row-chunks of ``A`` to bound memory."""
        a, b = _as_matrix(A), _as_matrix(B)
        rows_per_block = max(1, int(max_cells // max(1, len(b))))
        for start in range(0, len(a), rows_per_block):
            yield start, self.cdist(a[start : start + rows_per_block], b)

    def similarity(self, A, B) -> np.ndarray:
        return 1.0 - self.cdist(A, B)


def pairwise_param_distance(A, B, method: str = EUCLID, categorical_mask=None, weights=None) -> np.ndarray:
    """Functional wrapper around :class:`ParamDistance` for one-off use."""
    n_dims = _as_matrix(A).shape[1]
    return ParamDistance(n_dims, method=method, categorical_mask=categorical_mask, weights=weights).cdist(A, B)


def param_similarity(A, B, method: str = EUCLID, categorical_mask=None, weights=None) -> np.ndarray:
    return 1.0 - pairwise_param_distance(A, B, method=method, categorical_mask=categorical_mask, weights=weights)
