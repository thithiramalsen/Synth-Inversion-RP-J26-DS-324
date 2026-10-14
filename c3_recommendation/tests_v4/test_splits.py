"""Guide tests 4 and 5 - split integrity and the locked test split."""

import numpy as np
import pandas as pd
import pytest

from c3.splits import (
    BANK, TEST, VAL, LeakageError, Splits, TestSplitLocked, find_duplicate_groups, load_manifest,
    make_splits, save_splits,
)


def unit_frame(n=1000, d=4, seed=0):
    rng = np.random.default_rng(seed)
    ids = [f"s_{i:05d}" for i in range(n)]
    return pd.DataFrame(rng.random((n, d)), index=pd.Index(ids, name="sample_id"))


def test_splits_disjoint_complete_and_sized():
    params = unit_frame()
    result = make_splits(params, 0.1, 0.1, seed=7)
    sets = {s: set(result.manifest.loc[result.manifest.split == s, "sample_id"]) for s in (BANK, VAL, TEST)}
    assert not (sets[BANK] & sets[VAL]) and not (sets[BANK] & sets[TEST]) and not (sets[VAL] & sets[TEST])
    assert set().union(*sets.values()) == set(params.index)
    assert result.counts() == {BANK: 800, VAL: 100, TEST: 100}


def test_split_hash_reproducible_and_seed_sensitive(tmp_path):
    params = unit_frame()
    first, second = make_splits(params, 0.1, 0.1, seed=7), make_splits(params, 0.1, 0.1, seed=7)
    assert first.hashes() == second.hashes()
    assert make_splits(params, 0.1, 0.1, seed=8).hashes() != first.hashes()
    save_splits(first, tmp_path)
    assert load_manifest(tmp_path).equals(first.manifest)


def test_group_column_keeps_families_together():
    params = unit_frame(n=600)
    groups = pd.Series([f"family_{i // 6}" for i in range(600)], index=params.index, name="family")
    result = make_splits(params, 0.1, 0.1, seed=3, groups=groups)
    per_family = result.manifest.assign(family=groups.to_numpy()).groupby("family")["split"].nunique()
    assert (per_family == 1).all()
    assert result.counts()[VAL] > 0 and result.counts()[TEST] > 0


def test_exact_duplicates_follow_their_twin():
    params = unit_frame(n=200)
    params.iloc[150] = params.iloc[10].to_numpy() + 1e-12  # near-exact twin
    params.iloc[151] = params.iloc[10].to_numpy()          # exact twin
    assert find_duplicate_groups(params.to_numpy()) == [[10, 150, 151]]
    for seed in range(20):
        result = make_splits(params, 0.2, 0.2, seed=seed)
        labels = result.manifest.set_index("sample_id")["split"]
        assert labels.iloc[150] == labels.iloc[10] == labels.iloc[151]
        assert result.duplicate_groups == [[params.index[10], params.index[150], params.index[151]]]


def test_test_split_locked_without_flag_and_preregistration(tmp_path):
    manifest = make_splits(unit_frame(), 0.1, 0.1, seed=1).manifest
    prereg = tmp_path / "PREREGISTRATION.md"

    with pytest.raises(TestSplitLocked, match="final_test.enabled"):
        Splits(manifest, final_test_enabled=False, preregistration_path=prereg).get_targets(TEST, 5, 0)
    with pytest.raises(TestSplitLocked, match="missing or empty"):
        Splits(manifest, final_test_enabled=True, preregistration_path=prereg).ids(TEST)
    prereg.write_text("   \n")
    with pytest.raises(TestSplitLocked, match="missing or empty"):
        Splits(manifest, final_test_enabled=True, preregistration_path=prereg).ids(TEST)

    prereg.write_text("lambda* = 0.8\n")
    unlocked = Splits(manifest, final_test_enabled=True, preregistration_path=prereg)
    assert len(unlocked.get_targets(TEST, 5, 0)) == 5


def test_val_targets_seeded_and_bank_refused():
    splits = Splits(make_splits(unit_frame(), 0.1, 0.1, seed=1).manifest)
    assert splits.get_targets(VAL, 20, seed=4) == splits.get_targets(VAL, 20, seed=4)
    assert set(splits.get_targets(VAL, 20, seed=4)) <= set(splits.ids(VAL))
    with pytest.raises(LeakageError):
        splits.get_targets(BANK, 5, 0)
