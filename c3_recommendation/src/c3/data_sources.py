"""Data sources for parameters and audio.

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

from .audio_io import CorpusAudioReader, generation_running
from .config import C3Config
from .schema import ParamSchema, SchemaError

FULL_TABLE = "parameters_full.parquet"
NORMALIZED_TABLE = "parameters_normalized.parquet"
CORPUS_MANIFEST = "manifest.parquet"


class DataSource(Protocol):
    def sample_ids(self) -> pd.Index: ...
    def params_raw(self) -> pd.DataFrame: ...
    def params_normalized(self) -> pd.DataFrame: ...
    def params_unit(self) -> pd.DataFrame: ...
    def audio(self, sample_id: str) -> tuple[np.ndarray, int]: ...
    def iter_audio(self, sample_ids: Sequence[str], batch: int) -> Iterator: ...


def read_param_table(path: Path, schema: ParamSchema, suffix: str, id_column: str = "sample_id",
                     index_column: str = "sample_index") -> pd.DataFrame:
    """Read ``<name><suffix>`` columns, indexed by ID in ``sample_index`` order."""
    columns = [f"{name}{suffix}" for name in schema.names]
    table = pd.read_parquet(path, columns=[id_column, index_column, *columns])
    if table[id_column].duplicated().any():
        raise SchemaError(f"duplicated {id_column} values in {path.name}")
    if not table[index_column].is_monotonic_increasing:
        table = table.sort_values(index_column, kind="stable")
    frame = table.set_index(id_column)[columns]
    frame.columns = schema.names
    return frame


class _ParamTableSource:
    """Shared parameter access; subclasses set the table paths."""

    normalized_path: Path
    raw_path: Path

    def __init__(self, schema: ParamSchema, id_column: str, index_column: str, normalized_suffix: str):
        self.schema = schema
        self.id_column = id_column
        self.index_column = index_column
        self.normalized_suffix = normalized_suffix
        self._normalized: pd.DataFrame | None = None
        self._unit: pd.DataFrame | None = None
        self._raw: pd.DataFrame | None = None

    def _read(self, path: Path, suffix: str) -> pd.DataFrame:
        return read_param_table(path, self.schema, suffix, self.id_column, self.index_column)

    def params_normalized(self) -> pd.DataFrame:
        if self._normalized is None:
            frame = self._read(self.normalized_path, self.normalized_suffix)
            self.schema.validate(frame, scale="vital")
            self._normalized = frame
        return self._normalized

    def params_unit(self) -> pd.DataFrame:
        if self._unit is None:
            self._unit = self.schema.to_unit(self.params_normalized())
        return self._unit

    def params_raw(self) -> pd.DataFrame:
        if self._raw is None:
            frame = self._read(self.raw_path, "_raw")
            if not frame.index.equals(self.params_normalized().index):
                raise SchemaError("raw and normalized tables have different sample IDs or order")
            self._raw = frame
        return self._raw

    def sample_ids(self) -> pd.Index:
        return self.params_normalized().index


class ReferenceSource(_ParamTableSource):
    """Parameters from the teammate's verified ``reference/`` parquet tables. No audio."""

    def __init__(self, reference_dir: str | Path, schema: ParamSchema, id_column: str = "sample_id",
                 index_column: str = "sample_index", normalized_suffix: str = "_normalized"):
        super().__init__(schema, id_column, index_column, normalized_suffix)
        self.reference_dir = Path(reference_dir)
        self.normalized_path = self.reference_dir / NORMALIZED_TABLE
        self.raw_path = self.reference_dir / FULL_TABLE
        for path in (self.normalized_path, self.raw_path):
            if not path.exists():
                raise FileNotFoundError(f"missing reference table {path}")

    def audio(self, sample_id: str) -> tuple[np.ndarray, int]:
        raise NotImplementedError(
            "audio not available from reference source; switch data.source after Phase 5 gate"
        )

    def iter_audio(self, sample_ids: Sequence[str], batch: int) -> Iterator:
        raise NotImplementedError(
            "audio not available from reference source; switch data.source after Phase 5 gate"
        )


class CorpusV4Source(_ParamTableSource):
    """Own ``corpus_v4``: parameters from ``manifest.parquet``, audio from raw masters + DC on read."""

    def __init__(self, corpus_dir: str | Path, schema: ParamSchema, id_column: str = "sample_id",
                 index_column: str = "sample_index", normalized_suffix: str = "_normalized"):
        super().__init__(schema, id_column, index_column, normalized_suffix)
        self.corpus_dir = Path(corpus_dir)
        if not self.corpus_dir.exists():
            raise FileNotFoundError(f"corpus folder not found: {self.corpus_dir}")
        if generation_running(self.corpus_dir):
            raise RuntimeError(
                f"a generator holds the lock on {self.corpus_dir / '.run.lock'}: corpus generation is "
                "still running. Do not read corpus_v4 until it finishes and the Phase 5 audio gate passes."
            )
        self.normalized_path = self.raw_path = self.corpus_dir / CORPUS_MANIFEST
        if not self.normalized_path.exists():
            raise FileNotFoundError(f"{self.normalized_path} missing: the generator writes it only on completion")
        self._reader: CorpusAudioReader | None = None

    @property
    def reader(self) -> CorpusAudioReader:
        if self._reader is None:
            self._reader = CorpusAudioReader(self.corpus_dir)
        return self._reader

    def audio(self, sample_id: str) -> tuple[np.ndarray, int]:
        return self.reader.load(sample_id)

    def iter_audio(self, sample_ids: Sequence[str], batch: int = 64) -> Iterator:
        return self.reader.iter_batches(sample_ids, batch)


def load_schema(cfg: C3Config) -> ParamSchema:
    return ParamSchema.from_dataset_config(
        cfg.path("dataset_config_json"),
        categorical=cfg.get("data.categorical_columns") or (),
        expected_order=cfg.parameter_columns,
    )


def make_source(cfg: C3Config, schema: ParamSchema | None = None) -> DataSource:
    schema = schema or load_schema(cfg)
    kwargs = dict(
        id_column=cfg["data.id_column"],
        index_column=cfg.get("data.index_column", "sample_index"),
        normalized_suffix=cfg.get("data.normalized_column_suffix", "_normalized"),
    )
    source = cfg["data.source"]
    if source == "reference":
        return ReferenceSource(cfg.path("reference_dir"), schema, **kwargs)
    if source == "corpus_v4":
        return CorpusV4Source(cfg.path("corpus_dir"), schema, **kwargs)
    raise ValueError(f"unknown data.source {source!r}")
