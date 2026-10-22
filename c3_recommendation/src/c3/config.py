"""Load and validate ``configs/c3_v4.yaml``.

Paths in the YAML are relative to the repository root. The loader refuses to run while a
``<<FILL ...>>`` placeholder remains, and checks the keys every later phase relies on.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "c3_recommendation" / "configs" / "c3_v4.yaml"

PLACEHOLDER_MARK = "<<FILL"
VALID_SOURCES = ("reference", "corpus_v4")
VALID_DISTANCE_METHODS = ("auto", "euclid_sqrt_d", "gower")
VALID_RELEVANCE_SCALING = ("none", "pool_minmax")

REQUIRED_KEYS = (
    "run_name",
    "seed",
    "paths.reference_dir",
    "paths.corpus_dir",
    "paths.dataset_config_json",
    "paths.outputs_dir",
    "data.source",
    "data.id_column",
    "data.parameter_columns",
    "splits.val_fraction",
    "splits.test_fraction",
    "param_distance.method",
    "retrieval.pool_sizes",
    "selection.k_values",
    "selection.lambda_grid",
    "selection.relevance_scaling",
    "final_test.enabled",
)


class ConfigError(ValueError):
    """Raised when the configuration is incomplete or inconsistent."""


@dataclass(frozen=True)
class C3Config:
    raw: dict[str, Any]
    source_path: Path
    repo_root: Path = REPO_ROOT

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, dotted_key: str) -> Any:
        sentinel = object()
        value = self.get(dotted_key, sentinel)
        if value is sentinel:
            raise KeyError(dotted_key)
        return value

    def path(self, key: str) -> Path:
        """Resolve ``paths.<key>`` against the repository root."""
        value = Path(self[f"paths.{key}"])
        return value if value.is_absolute() else (self.repo_root / value).resolve()

    @property
    def seed(self) -> int:
        return int(self["seed"])

    @property
    def parameter_columns(self) -> list[str]:
        return list(self["data.parameter_columns"])

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.raw)


def _find_placeholders(node: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found += _find_placeholders(value, f"{prefix}{key}.")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += _find_placeholders(value, f"{prefix}{index}.")
    elif isinstance(node, str) and PLACEHOLDER_MARK in node:
        found.append(prefix.rstrip("."))
    return found


def validate_config(raw: dict[str, Any]) -> None:
    placeholders = _find_placeholders(raw)
    if placeholders:
        raise ConfigError(f"unfilled placeholders in config: {placeholders}")

    probe = C3Config(raw=raw, source_path=Path("<memory>"))
    missing = [key for key in REQUIRED_KEYS if probe.get(key) is None]
    if missing:
        raise ConfigError(f"missing required config keys: {missing}")

    if probe["data.source"] not in VALID_SOURCES:
        raise ConfigError(f"data.source must be one of {VALID_SOURCES}")
    if probe["param_distance.method"] not in VALID_DISTANCE_METHODS:
        raise ConfigError(f"param_distance.method must be one of {VALID_DISTANCE_METHODS}")
    if probe["selection.relevance_scaling"] not in VALID_RELEVANCE_SCALING:
        raise ConfigError(f"selection.relevance_scaling must be one of {VALID_RELEVANCE_SCALING}")

    columns = probe["data.parameter_columns"]
    if not isinstance(columns, list) or not columns or len(set(columns)) != len(columns):
        raise ConfigError("data.parameter_columns must be a non-empty list of unique names")

    val, test = float(probe["splits.val_fraction"]), float(probe["splits.test_fraction"])
    if not (0 < val < 1 and 0 < test < 1 and val + test < 1):
        raise ConfigError("split fractions must be in (0, 1) and sum to less than 1")

    lambdas = probe["selection.lambda_grid"]
    if not lambdas or any(not 0.0 <= float(lam) <= 1.0 for lam in lambdas):
        raise ConfigError("selection.lambda_grid values must lie in [0, 1]")
    if any(int(k) < 1 for k in probe["selection.k_values"]):
        raise ConfigError("selection.k_values must be positive")
    if any(int(n) < max(int(k) for k in probe["selection.k_values"]) for n in probe["retrieval.pool_sizes"]):
        raise ConfigError("every retrieval pool size must be at least the largest k")
    if not isinstance(probe["final_test.enabled"], bool):
        raise ConfigError("final_test.enabled must be true or false")


def load_config(path: str | Path | None = None) -> C3Config:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = (REPO_ROOT / config_path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    validate_config(raw)
    return C3Config(raw=raw, source_path=config_path)
