"""Parameter schema built from the dataset config JSON.

Three scales exist for every control (see docs/DATA_CONTRACT.md):

* ``vital``  - Vital normalized slider value, inside the control's ``[min, max]`` interval.
               This is what ``parameters_normalized.parquet`` stores.
* ``unit``   - ``(vital - min) / (max - min)``, in ``[0, 1]``. C3 distances use this scale.
* ``raw``    - Vital internal value (seconds, dB, ...); informational only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

UNIT_RULE = "vital_normalized_minmax"
CONTINUOUS = "continuous"
CATEGORICAL = "categorical"
RANGE_TOLERANCE = 1e-6


class SchemaError(ValueError):
    """Raised when a parameter table does not match the schema."""


@dataclass(frozen=True)
class ParamSpec:
    name: str
    control: str | None
    kind: str
    min: float
    max: float

    @property
    def span(self) -> float:
        return self.max - self.min


@dataclass(frozen=True)
class ParamSchema:
    params: tuple[ParamSpec, ...]
    unit_rule: str = UNIT_RULE

    @classmethod
    def from_dataset_config(
        cls,
        config: str | Path | Mapping[str, Any],
        categorical: Iterable[str] = (),
        expected_order: Iterable[str] | None = None,
    ) -> "ParamSchema":
        if not isinstance(config, Mapping):
            config = json.loads(Path(config).read_text(encoding="utf-8"))
        order = list(config["parameter_order"])
        if expected_order is not None and list(expected_order) != order:
            raise SchemaError(
                f"parameter order in run config {list(expected_order)} differs from dataset config {order}"
            )
        categorical = set(categorical)
        unknown = categorical - set(order)
        if unknown:
            raise SchemaError(f"categorical columns not in schema: {sorted(unknown)}")
        specs = []
        for name in order:
            entry = config["parameters"][name]
            lo, hi = float(entry["min"]), float(entry["max"])
            if not hi > lo:
                raise SchemaError(f"{name}: max must exceed min")
            specs.append(
                ParamSpec(
                    name=name,
                    control=entry.get("control"),
                    kind=CATEGORICAL if name in categorical else CONTINUOUS,
                    min=lo,
                    max=hi,
                )
            )
        return cls(params=tuple(specs))

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.params]

    @property
    def mins(self) -> np.ndarray:
        return np.array([p.min for p in self.params], dtype=np.float64)

    @property
    def maxs(self) -> np.ndarray:
        return np.array([p.max for p in self.params], dtype=np.float64)

    @property
    def categorical_mask(self) -> np.ndarray:
        return np.array([p.kind == CATEGORICAL for p in self.params], dtype=bool)

    @property
    def all_continuous(self) -> bool:
        return not self.categorical_mask.any()

    def __len__(self) -> int:
        return len(self.params)

    # ------------------------------------------------------------------ conversion
    def to_unit(self, vital: pd.DataFrame) -> pd.DataFrame:
        """Vital normalized values -> unit scale, after validating the input."""
        self.validate(vital, scale="vital")
        unit = (vital.to_numpy(dtype=np.float64) - self.mins) / (self.maxs - self.mins)
        return pd.DataFrame(unit, index=vital.index, columns=self.names)

    def from_unit(self, unit: pd.DataFrame) -> pd.DataFrame:
        """Unit scale -> Vital normalized values (inverse of ``to_unit``)."""
        self.validate(unit, scale="unit")
        vital = self.mins + unit.to_numpy(dtype=np.float64) * (self.maxs - self.mins)
        return pd.DataFrame(vital, index=unit.index, columns=self.names)

    # ------------------------------------------------------------------ validation
    def validate(self, df: pd.DataFrame, scale: str = "unit", tol: float = RANGE_TOLERANCE) -> None:
        """Check column presence/order, NaNs and value ranges for ``scale`` ('vital' or 'unit')."""
        if list(df.columns) != self.names:
            missing = [n for n in self.names if n not in df.columns]
            extra = [c for c in df.columns if c not in self.names]
            raise SchemaError(
                f"columns must match schema order {self.names}; missing={missing}, extra={extra}"
            )
        values = df.to_numpy(dtype=np.float64)
        if np.isnan(values).any():
            bad = [n for n, has in zip(self.names, np.isnan(values).any(axis=0)) if has]
            raise SchemaError(f"NaN values in columns {bad}")
        if scale == "vital":
            lo, hi = self.mins, self.maxs
        elif scale == "unit":
            lo, hi = np.zeros(len(self)), np.ones(len(self))
        else:
            raise ValueError(f"unknown scale {scale!r}")
        below = (values < lo - tol).any(axis=0)
        above = (values > hi + tol).any(axis=0)
        if below.any() or above.any():
            bad = [n for n, b, a in zip(self.names, below, above) if b or a]
            raise SchemaError(f"values out of {scale} range in columns {bad}")
