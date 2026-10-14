"""ReferenceSource on synthetic parquet tables; CorpusV4Source lock guard."""

import numpy as np
import pytest

from c3.data_sources import CorpusV4Source, ReferenceSource
from c3.schema import SchemaError

from conftest import make_reference_tables


@pytest.fixture
def reference_dir(tmp_path, schema):
    full, norm = make_reference_tables(schema)
    # Store rows shuffled to check the source restores sample_index order.
    full.sample(frac=1, random_state=0).to_parquet(tmp_path / "parameters_full.parquet", index=False)
    norm.sample(frac=1, random_state=0).to_parquet(tmp_path / "parameters_normalized.parquet", index=False)
    return tmp_path, full


def test_reference_source_returns_schema_order_and_index_order(reference_dir, schema):
    path, full = reference_dir
    source = ReferenceSource(path, schema)
    vital = source.params_normalized()
    assert list(vital.columns) == schema.names
    assert list(vital.index) == list(full["sample_id"])  # numeric order, not string order
    assert vital.index.name == "sample_id"


def test_reference_source_unit_scale_matches_sample_01(reference_dir, schema):
    path, full = reference_dir
    unit = ReferenceSource(path, schema).params_unit()
    expected = full[[f"{n}_sample_01" for n in schema.names]].to_numpy()
    assert np.allclose(unit.to_numpy(), expected, atol=1e-12)


def test_reference_source_raw_aligned(reference_dir, schema):
    path, full = reference_dir
    raw = ReferenceSource(path, schema).params_raw()
    assert np.allclose(raw["bend_amount"].to_numpy(), full["bend_amount_raw"].to_numpy())


def test_reference_source_rejects_out_of_range(tmp_path, schema):
    full, norm = make_reference_tables(schema)
    norm.loc[0, "filter_env_amount_normalized"] = 0.9
    full.to_parquet(tmp_path / "parameters_full.parquet", index=False)
    norm.to_parquet(tmp_path / "parameters_normalized.parquet", index=False)
    with pytest.raises(SchemaError):
        ReferenceSource(tmp_path, schema).params_normalized()


def test_reference_source_has_no_audio(reference_dir, schema):
    path, full = reference_dir
    with pytest.raises(NotImplementedError, match="Phase 5"):
        ReferenceSource(path, schema).audio(full["sample_id"][0])


def test_corpus_source_refuses_while_generation_runs(tmp_path, schema):
    (tmp_path / ".run.lock").write_text("1")
    with pytest.raises(RuntimeError, match="still running"):
        CorpusV4Source(tmp_path, schema)


def test_corpus_source_is_skeleton_without_lock(tmp_path, schema):
    source = CorpusV4Source(tmp_path, schema)
    with pytest.raises(NotImplementedError):
        source.params_unit()
