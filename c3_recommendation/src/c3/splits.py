"""Deterministic bank / val / test split, duplicate guard and the locked test split.

* Splitting is by sample, or by group when a group column exists (whole group on one side).
* Exact-duplicate guard: parameter vectors within ``dup_tol`` (max-abs, unit scale) are
  moved into the split of their earliest member (lowest position in sample order).
* Test targets are locked (rule R6): :func:`get_targets` / :meth:`Splits.ids` for ``"test"``
  raise unless ``final_test.enabled`` is true AND ``docs/PREREGISTRATION.md`` is non-empty.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .config import REPO_ROOT, C3Config

BANK, VAL, TEST = "bank", "val", "test"
SPLIT_NAMES = (BANK, VAL, TEST)
DEFAULT_PREREGISTRATION = REPO_ROOT / "c3_recommendation" / "docs" / "PREREGISTRATION.md"
MANIFEST_NAME = "split_manifest.parquet"
SUMMARY_NAME = "split_summary.json"


class TestSplitLocked(PermissionError):
    """Raised when test targets are requested before preregistration."""

    __test__ = False  # not a pytest test class


class LeakageError(AssertionError):
    """Raised when a target could reach the searchable bank or splits overlap."""


# ---------------------------------------------------------------------- hashing
def ids_sha256(ids: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(sorted(map(str, ids))).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------- duplicate guard
def find_duplicate_groups(unit: np.ndarray, tol: float = 1e-9) -> list[list[int]]:
    """Connected components of rows whose vectors are within ``tol`` (max-abs) of each other."""
    pairs = cKDTree(unit).query_pairs(r=tol, p=np.inf, output_type="ndarray")
    if len(pairs) == 0:
        return []
    parent = np.arange(len(unit))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    members: dict[int, list[int]] = {}
    for i in np.unique(pairs):
        members.setdefault(root(int(i)), []).append(int(i))
    return [sorted(group) for _, group in sorted(members.items())]


# ---------------------------------------------------------------------- split result
@dataclass
class SplitResult:
    manifest: pd.DataFrame  # columns: sample_id, split  (sample order)
    seed: int
    val_fraction: float
    test_fraction: float
    group_column: str | None
    duplicate_groups: list[list[str]] = field(default_factory=list)
    duplicate_moves: list[dict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {name: int((self.manifest["split"] == name).sum()) for name in SPLIT_NAMES}

    def hashes(self) -> dict[str, str]:
        return {
            name: ids_sha256(self.manifest.loc[self.manifest["split"] == name, "sample_id"])
            for name in SPLIT_NAMES
        }

    def summary(self) -> dict:
        return {
            "seed": self.seed,
            "val_fraction": self.val_fraction,
            "test_fraction": self.test_fraction,
            "group_column": self.group_column,
            "grouping": "by group" if self.group_column else "independent samples",
            "n_total": int(len(self.manifest)),
            "counts": self.counts(),
            "sha256_sorted_ids": self.hashes(),
            "duplicate_groups": self.duplicate_groups,
            "duplicate_moves": self.duplicate_moves,
        }


def _assign_units(sizes: np.ndarray, n_val: int, n_test: int, rng: np.random.Generator) -> np.ndarray:
    """Shuffle units (samples or groups) and fill test, then val, then bank by size."""
    order = rng.permutation(len(sizes))
    labels = np.empty(len(sizes), dtype=object)
    cumulative = np.cumsum(sizes[order])
    labels[order] = np.where(cumulative <= n_test, TEST, np.where(cumulative <= n_test + n_val, VAL, BANK))
    return labels


def make_splits(
    unit_params: pd.DataFrame,
    val_fraction: float,
    test_fraction: float,
    seed: int,
    groups: pd.Series | None = None,
    dup_tol: float = 1e-9,
) -> SplitResult:
    """Split the sample IDs of ``unit_params`` (index = sample_id, rows in sample order)."""
    ids = unit_params.index.to_numpy()
    if pd.Index(ids).has_duplicates:
        raise ValueError("sample IDs must be unique")
    n = len(ids)
    n_test, n_val = int(round(n * test_fraction)), int(round(n * val_fraction))
    rng = np.random.default_rng(seed)

    if groups is None:
        labels = _assign_units(np.ones(n, dtype=int), n_val, n_test, rng)
    else:
        groups = groups.reindex(unit_params.index)
        if groups.isna().any():
            raise ValueError("group column has missing values")
        codes, uniques = pd.factorize(groups, sort=True)
        unit_labels = _assign_units(np.bincount(codes), n_val, n_test, rng)
        labels = unit_labels[codes]

    labels = labels.astype(object)
    duplicate_groups, moves = [], []
    for members in find_duplicate_groups(unit_params.to_numpy(dtype=np.float64), tol=dup_tol):
        duplicate_groups.append([str(ids[i]) for i in members])
        anchor_split = labels[members[0]]
        for i in members[1:]:
            if labels[i] != anchor_split:
                moves.append({"sample_id": str(ids[i]), "from": labels[i], "to": anchor_split,
                              "twin": str(ids[members[0]])})
                labels[i] = anchor_split

    manifest = pd.DataFrame({"sample_id": ids, "split": labels.astype(str)})
    result = SplitResult(manifest, seed, val_fraction, test_fraction,
                         None if groups is None else groups.name, duplicate_groups, moves)
    assert_valid_split(result.manifest, ids, groups)
    return result


def assert_valid_split(manifest: pd.DataFrame, all_ids: Sequence[str], groups: pd.Series | None = None) -> None:
    sets = {name: set(manifest.loc[manifest["split"] == name, "sample_id"]) for name in SPLIT_NAMES}
    for i, a in enumerate(SPLIT_NAMES):
        for b in SPLIT_NAMES[i + 1 :]:
            if sets[a] & sets[b]:
                raise LeakageError(f"splits {a} and {b} overlap")
    if set().union(*sets.values()) != set(all_ids) or len(manifest) != len(all_ids):
        raise LeakageError("split union does not equal the full ID set")
    if groups is not None:
        per_group = pd.Series(manifest["split"].to_numpy(), index=manifest["sample_id"]).groupby(
            groups.reindex(manifest["sample_id"]).to_numpy()
        ).nunique()
        if (per_group > 1).any():
            raise LeakageError("a group straddles more than one split")


# ---------------------------------------------------------------------- persistence
def save_splits(result: SplitResult, out_dir: str | Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.manifest.to_parquet(out_dir / MANIFEST_NAME, index=False)
    summary = result.summary()
    (out_dir / SUMMARY_NAME).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def load_manifest(out_dir: str | Path) -> pd.DataFrame:
    return pd.read_parquet(Path(out_dir) / MANIFEST_NAME)


# ---------------------------------------------------------------------- locked access
def assert_test_access(final_test_enabled: bool, preregistration_path: str | Path | None = None) -> None:
    path = Path(preregistration_path) if preregistration_path is not None else DEFAULT_PREREGISTRATION
    if not final_test_enabled:
        raise TestSplitLocked("test split is locked: final_test.enabled is false")
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        raise TestSplitLocked(f"test split is locked: {path} is missing or empty")


class Splits:
    """Read access to a split manifest that enforces the test lock."""

    def __init__(self, manifest: pd.DataFrame, final_test_enabled: bool = False,
                 preregistration_path: str | Path | None = None):
        self._manifest = manifest
        self._final_test_enabled = final_test_enabled
        self._preregistration_path = preregistration_path

    @classmethod
    def from_config(cls, cfg: C3Config, manifest: pd.DataFrame) -> "Splits":
        return cls(manifest, final_test_enabled=bool(cfg["final_test.enabled"]))

    def ids(self, split: str) -> list[str]:
        if split not in SPLIT_NAMES:
            raise ValueError(f"unknown split {split!r}")
        if split == TEST:
            assert_test_access(self._final_test_enabled, self._preregistration_path)
        return self._manifest.loc[self._manifest["split"] == split, "sample_id"].tolist()

    def get_targets(self, split: str, n: int, seed: int) -> list[str]:
        """Seeded sample of ``n`` evaluation targets from ``split`` (``val`` or locked ``test``)."""
        if split == BANK:
            raise LeakageError("evaluation targets must come from val or test, not the bank")
        pool = self.ids(split)
        if n > len(pool):
            raise ValueError(f"requested {n} targets but split {split!r} has {len(pool)}")
        rng = np.random.default_rng(seed)
        return [pool[i] for i in rng.choice(len(pool), size=n, replace=False)]
