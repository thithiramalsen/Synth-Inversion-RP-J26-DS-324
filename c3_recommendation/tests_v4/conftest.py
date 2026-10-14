"""Shared synthetic fixtures - tests never need the real dataset."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from c3.schema import ParamSchema

DATASET_CONFIG = {
    "parameter_order": ["wave_frame", "bend_amount", "filter_env_amount"],
    "parameters": {
        "wave_frame": {"control": "osc_1_wave_frame", "mode": "normalized", "min": 0.0, "max": 1.0},
        "bend_amount": {"control": "osc_1_distortion_amount", "mode": "normalized", "min": 0.25, "max": 0.75},
        "filter_env_amount": {"control": "modulation_1_amount", "mode": "normalized", "min": 0.5, "max": 0.5625},
    },
}


@pytest.fixture
def dataset_config() -> dict:
    return {"parameter_order": list(DATASET_CONFIG["parameter_order"]),
            "parameters": {k: dict(v) for k, v in DATASET_CONFIG["parameters"].items()}}


@pytest.fixture
def schema(dataset_config) -> ParamSchema:
    return ParamSchema.from_dataset_config(dataset_config)


def make_reference_tables(schema: ParamSchema, n: int = 12, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic parameters_full / parameters_normalized tables with the real column layout."""
    rng = np.random.default_rng(seed)
    unit = rng.random((n, len(schema)))
    vital = schema.mins + unit * (schema.maxs - schema.mins)
    # Real IDs grow from 5 to 6 digits, so string order differs from numeric order.
    index = np.arange(n) * 20000
    ids = [f"restricted_bend_sustain_v4_{i:05d}" for i in index]
    full = pd.DataFrame({"sample_id": ids, "sample_index": index})
    norm = full.copy()
    for j, name in enumerate(schema.names):
        full[f"{name}_sample_01"] = unit[:, j]
        full[f"{name}_normalized"] = vital[:, j]
        full[f"{name}_raw"] = vital[:, j] * 10.0
        full[f"{name}_display"] = [f"{v:.6f}" for v in vital[:, j] * 10.0]
        norm[f"{name}_normalized"] = vital[:, j]
    return full, norm


@contextmanager
def hold_generator_lock(corpus_dir: Path):
    """Hold the 1-byte OS lock on .run.lock exactly like generation/generate_corpus.py does."""
    with (Path(corpus_dir) / ".run.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
