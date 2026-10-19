"""Config loading and validation."""

import copy

import pytest
import yaml

from c3.config import DEFAULT_CONFIG_PATH, REPO_ROOT, ConfigError, load_config, validate_config


@pytest.fixture
def raw_config() -> dict:
    with DEFAULT_CONFIG_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_repository_config_loads_and_resolves_paths():
    cfg = load_config()
    assert cfg.path("outputs_dir") == (REPO_ROOT / "c3_recommendation" / "outputs" / "v4").resolve()
    assert len(cfg.parameter_columns) == 13
    assert cfg["final_test.enabled"] is False


def test_placeholder_is_refused(raw_config):
    raw = copy.deepcopy(raw_config)
    raw["data"]["id_column"] = "<<FILL FROM PHASE 0>>"
    with pytest.raises(ConfigError, match="placeholders.*data.id_column"):
        validate_config(raw)


def test_missing_key_is_refused(raw_config):
    raw = copy.deepcopy(raw_config)
    del raw["paths"]["corpus_dir"]
    with pytest.raises(ConfigError, match="paths.corpus_dir"):
        validate_config(raw)


@pytest.mark.parametrize(
    "dotted,value",
    [
        ("splits.val_fraction", 0.95),  # 0.95 + 0.10 test >= 1
        ("data.source", "audio"),
        ("selection.lambda_grid", [1.2]),
        ("retrieval.pool_sizes", [2]),
        ("final_test.enabled", "yes"),
    ],
)
def test_invalid_values_are_refused(raw_config, dotted, value):
    raw = copy.deepcopy(raw_config)
    section, key = dotted.split(".")
    raw[section][key] = value
    with pytest.raises(ConfigError):
        validate_config(raw)
