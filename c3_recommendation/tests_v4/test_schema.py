"""Guide tests 2 and 3 - schema validation and normalisation round-trip."""

import numpy as np
import pandas as pd
import pytest

from c3.schema import ParamSchema, SchemaError


def unit_frame(schema, rows):
    return pd.DataFrame(rows, columns=schema.names, dtype=float)


def test_schema_reads_order_and_ranges(schema):
    assert schema.names == ["wave_frame", "bend_amount", "filter_env_amount"]
    assert np.allclose(schema.mins, [0.0, 0.25, 0.5])
    assert np.allclose(schema.maxs, [1.0, 0.75, 0.5625])
    assert schema.all_continuous


def test_validate_accepts_valid_unit_frame(schema):
    schema.validate(unit_frame(schema, [[0.0, 0.5, 1.0]]), scale="unit")


def test_validate_rejects_out_of_range(schema):
    with pytest.raises(SchemaError, match="out of unit range"):
        schema.validate(unit_frame(schema, [[0.0, 1.2, 0.5]]), scale="unit")
    # 0.6 is inside [0, 1] but outside filter_env_amount's vital range [0.5, 0.5625]
    with pytest.raises(SchemaError, match="out of vital range"):
        schema.validate(unit_frame(schema, [[0.5, 0.5, 0.6]]), scale="vital")


def test_validate_rejects_missing_column(schema):
    frame = unit_frame(schema, [[0.1, 0.2, 0.3]]).drop(columns="bend_amount")
    with pytest.raises(SchemaError, match="missing=\\['bend_amount'\\]"):
        schema.validate(frame)


def test_validate_rejects_wrong_order(schema):
    frame = unit_frame(schema, [[0.1, 0.2, 0.3]])[["bend_amount", "wave_frame", "filter_env_amount"]]
    with pytest.raises(SchemaError, match="schema order"):
        schema.validate(frame)


def test_validate_rejects_nan(schema):
    with pytest.raises(SchemaError, match="NaN"):
        schema.validate(unit_frame(schema, [[0.1, np.nan, 0.3]]))


def test_expected_order_mismatch_raises(dataset_config):
    with pytest.raises(SchemaError, match="differs"):
        ParamSchema.from_dataset_config(dataset_config, expected_order=["bend_amount", "wave_frame"])


def test_normalisation_round_trip_hand_computed(schema):
    # wave_frame [0, 1]: 0.4 -> 0.4; bend [0.25, 0.75]: 0.5 -> 0.5; env amount [0.5, 0.5625]: 0.53125 -> 0.5
    vital = pd.DataFrame([[0.4, 0.5, 0.53125], [0.0, 0.75, 0.5]], columns=schema.names)
    unit = schema.to_unit(vital)
    assert np.allclose(unit.to_numpy(), [[0.4, 0.5, 0.5], [0.0, 1.0, 0.0]])
    assert np.allclose(schema.from_unit(unit).to_numpy(), vital.to_numpy())
