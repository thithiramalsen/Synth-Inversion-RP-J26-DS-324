"""Data sources for parameters (and, after the Phase 5 gate, audio).

All parameter frames are indexed by ``sample_id`` in ``sample_index`` order, with columns
in schema order. Scales are described in :mod:`c3.schema`:

* ``params_normalized()`` - Vital normalized values (inside each control's [min, max])
* ``params_unit()``       - unit scale [0, 1]; what C3 distances use
* ``params_raw()``        - Vital internal values (seconds, dB, ...); informational
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Protocol, Sequence

import numpy as np
import pandas as pd

from .config import C3Config
from .schema import ParamSchema, SchemaError

FULL_TABLE = "parameters_full.parquet"
NORMALIZED_TABLE = "parameters_normalized.parquet"
RUN_LOCK = ".run.lock"


class DataSource(Protocol):
    def sample_ids(self) -> pd.Index: ...
    def params_raw(self) -> pd.DataFrame: ...
    def params_normalized(self) -> pd.DataFrame: ...
    def params_unit(self) -> pd.DataFrame: ...
    def audio(self, sample_id: str) -> tuple[np.ndarray, int]: ...
    def iter_audio(self, sample_ids: Sequence[str], batch: int) -> Iterator: ...


class ReferenceSource:
    """Parameters from the teammate's verified ``reference/`` parquet tables. No audio."""

    def __init__(
        self,
        reference_dir: str | Path,
        schema: ParamSchema,
        id_column: str = "sample_id",
        index_column: str = "sample_index",
        normalized_suffix: str = "_normalized",
    ):
        self.reference_dir = Path(reference_dir)
        self.schema = schema
        self.id_column = id_column
        self.index_column = index_column
        self.normalized_suffix = normalized_suffix
        self._normalized: pd.DataFrame | None = None
        self._unit: pd.DataFrame | None = None
        self._raw: pd.DataFrame | None = None
        for name in (FULL_TABLE, NORMALIZED_TABLE):
            if not (self.reference_dir / name).exists():
                raise FileNotFoundError(f"missing reference table {self.reference_dir / name}")

    def _read(self, filename: str, suffix: str) -> pd.DataFrame:
        columns = [f"{name}{suffix}" for name in self.schema.names]
        table = pd.read_parquet(self.reference_dir / filename, columns=[self.id_column, self.index_column, *columns])
        if table[self.id_column].duplicated().any():
            raise SchemaError(f"duplicated {self.id_column} values in {filename}")
        if not table[self.index_column].is_monotonic_increasing:
            table = table.sort_values(self.index_column, kind="stable")
        frame = table.set_index(self.id_column)[columns]
        frame.columns = self.schema.names
        return frame

    def params_normalized(self) -> pd.DataFrame:
        if self._normalized is None:
            frame = self._read(NORMALIZED_TABLE, self.normalized_suffix)
            self.schema.validate(frame, scale="vital")
            self._normalized = frame
        return self._normalized

    def params_unit(self) -> pd.DataFrame:
        if self._unit is None:
            self._unit = self.schema.to_unit(self.params_normalized())
        return self._unit

    def params_raw(self) -> pd.DataFrame:
        if self._raw is None:
            frame = self._read(FULL_TABLE, "_raw")
            if not frame.index.equals(self.params_normalized().index):
                raise SchemaError("full and normalized tables have different sample IDs or order")
            self._raw = frame
        return self._raw

    def sample_ids(self) -> pd.Index:
        return self.params_normalized().index

    def audio(self, sample_id: str) -> tuple[np.ndarray, int]:
        raise NotImplementedError(
            "audio not available from reference source; switch data.source after Phase 5 gate"
        )

    def iter_audio(self, sample_ids: Sequence[str], batch: int) -> Iterator:
        raise NotImplementedError(
            "audio not available from reference source; switch data.source after Phase 5 gate"
        )


class CorpusV4Source:
    """Own ``corpus_v4`` audio corpus. Skeleton until the Phase 5 audio gate."""

    def __init__(self, corpus_dir: str | Path, schema: ParamSchema):
        self.corpus_dir = Path(corpus_dir)
        self.schema = schema
        if (self.corpus_dir / RUN_LOCK).exists():
            raise RuntimeError(
                f"{self.corpus_dir / RUN_LOCK} exists: corpus generation is still running. "
                "Do not read corpus_v4 until it finishes and the Phase 5 audio gate passes."
            )
        if not self.corpus_dir.exists():
            raise FileNotFoundError(f"corpus folder not found: {self.corpus_dir}")

    def _phase5(self, *_args, **_kwargs):
        raise NotImplementedError("CorpusV4Source is implemented in Phase 5 (audio gate)")

    sample_ids = params_raw = params_normalized = params_unit = audio = iter_audio = _phase5


def load_schema(cfg: C3Config) -> ParamSchema:
    return ParamSchema.from_dataset_config(
        cfg.path("dataset_config_json"),
        categorical=cfg.get("data.categorical_columns") or (),
        expected_order=cfg.parameter_columns,
    )


def make_source(cfg: C3Config, schema: ParamSchema | None = None) -> DataSource:
    schema = schema or load_schema(cfg)
    source = cfg["data.source"]
    if source == "reference":
        return ReferenceSource(
            cfg.path("reference_dir"),
            schema,
            id_column=cfg["data.id_column"],
            index_column=cfg.get("data.index_column", "sample_index"),
            normalized_suffix=cfg.get("data.normalized_column_suffix", "_normalized"),
        )
    if source == "corpus_v4":
        return CorpusV4Source(cfg.path("corpus_dir"), schema)
    raise ValueError(f"unknown data.source {source!r}")
