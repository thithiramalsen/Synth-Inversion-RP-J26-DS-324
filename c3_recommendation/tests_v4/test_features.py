"""Feature extraction (legacy continuity, batching) and feature cosine relevance."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import soundfile as sf

from c3.features import FeatureExtractor, FeatureSettings, extract_corpus, load_feature_cache
from c3.relevance import FeatureCosineRelevance

from test_audio_io import N, SR, make_recipe

LEGACY = Path(__file__).resolve().parents[1] / "pipeline.py"


def tone(freq, n=SR // 4, seed=0):
    t = np.arange(n) / SR
    noise = np.random.default_rng(seed).standard_normal(n) * 0.01
    return 0.3 * np.sin(2 * np.pi * freq * t) + noise


@pytest.fixture(scope="module")
def legacy():
    spec = importlib.util.spec_from_file_location("legacy_pipeline_v1", LEGACY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["legacy_pipeline_v1"] = module
    spec.loader.exec_module(module)
    return module


def test_mfcc26_equals_legacy_prototype(legacy):
    settings = {"sample_rate": SR, "n_fft": 2048, "hop_length": 512, "n_mels": 40, "n_mfcc": 13,
                "f_min_hz": 20.0, "f_max_hz": 20000.0}
    extractor = FeatureExtractor()
    for freq in (110.0, 440.0, 2500.0):
        audio = tone(freq)
        assert np.array_equal(extractor.extract(audio, SR)["mfcc26"], legacy.extract_mfcc_summary(audio, settings))


def test_shapes_and_rate_check():
    features = FeatureExtractor().extract(tone(440.0), SR)
    assert features["mfcc26"].shape == (26,) and features["logmel_stats"].shape == (128,)
    with pytest.raises(ValueError, match="Hz"):
        FeatureExtractor().extract(tone(440.0), 22050)


@pytest.fixture
def tiny_corpus(tmp_path):
    (tmp_path / "raw_float").mkdir()
    (tmp_path / "recipe.json").write_text(json.dumps(make_recipe()))
    ids = [f"s_{i:03d}" for i in range(7)]
    for i, sid in enumerate(ids):
        sf.write(tmp_path / "raw_float" / f"{sid}.wav", tone(200.0 * (i + 1), n=N, seed=i).astype(np.float32),
                 SR, subtype="FLOAT")
    return tmp_path, ids


def test_extract_corpus_serial_parallel_and_single_agree(tiny_corpus):
    from c3.audio_io import CorpusAudioReader

    path, ids = tiny_corpus
    serial = extract_corpus(path, ids, workers=1, chunk=3)
    parallel = extract_corpus(path, ids, workers=2, chunk=2)
    reader, extractor = CorpusAudioReader(path), FeatureExtractor()
    single = extractor.extract(*reader.load(ids[4]))
    for rep in serial:
        assert np.array_equal(serial[rep], parallel[rep])
        assert np.array_equal(serial[rep][4], single[rep])


def test_load_feature_cache_checks_shape(tmp_path):
    np.save(tmp_path / "mfcc26.npy", np.zeros((3, 26)))
    pd.DataFrame({"sample_id": ["a", "b", "c"]}).to_parquet(tmp_path / "feature_index.parquet")
    meta = {"representations": {"mfcc26": {"file": "mfcc26.npy", "dims": 26}}, "settings": FeatureSettings().as_dict()}
    (tmp_path / "features_meta.json").write_text(json.dumps(meta))
    array, ids, _ = load_feature_cache(tmp_path, "mfcc26")
    assert array.shape == (3, 26) and ids == ["a", "b", "c"]
    np.save(tmp_path / "mfcc26.npy", np.zeros((2, 26)))
    with pytest.raises(ValueError, match="shape"):
        load_feature_cache(tmp_path, "mfcc26")


# ---------------------------------------------------------------------- relevance
@pytest.fixture
def feature_relevance():
    rng = np.random.default_rng(0)
    ids = [f"s_{i:03d}" for i in range(60)]
    features = rng.normal(size=(60, 5)) * [1, 10, 100, 1, 0.1] + [0, 5, -3, 2, 1]
    return FeatureCosineRelevance("toy", features, ids), ids, features


def test_standardised_with_bank_only(feature_relevance):
    relevance, ids, features = feature_relevance
    bank = ids[:40]
    relevance.fit(bank)
    assert np.allclose(relevance.mean, features[:40].mean(axis=0))
    shifted = features.copy()
    shifted[40:] += 1000.0  # val/test rows must not move the scaler
    other = FeatureCosineRelevance("toy", shifted, ids)
    other.fit(bank)
    assert np.array_equal(other.mean, relevance.mean) and np.array_equal(other.std, relevance.std)


def test_self_relevance_one_and_bank_scores_consistent(feature_relevance):
    relevance, ids, _ = feature_relevance
    relevance.fit(ids[:40])
    assert relevance.score_ids("s_050", ["s_050"])[0] == pytest.approx(1.0)
    assert np.allclose(relevance.score_bank("s_050"), relevance.score_ids("s_050", ids[:40]))
    scores = relevance.score_bank("s_041")
    assert scores.max() <= 1.0 + 1e-12 and scores.min() >= -1.0 - 1e-12


def test_zero_variance_dimension_reported():
    ids = [f"s_{i}" for i in range(10)]
    features = np.column_stack([np.arange(10.0), np.full(10, 3.0)])
    relevance = FeatureCosineRelevance("toy", features, ids)
    relevance.fit(ids)
    assert relevance.describe()["zero_variance_dims"] == [1]


def test_score_audio_matches_stored_features():
    extractor = FeatureExtractor()
    clips = [tone(f, seed=i) for i, f in enumerate((150.0, 300.0, 600.0, 1200.0, 2400.0))]
    features = np.vstack([extractor.extract(c, SR)["mfcc26"] for c in clips])
    ids = [f"c{i}" for i in range(5)]
    relevance = FeatureCosineRelevance("mfcc26", features, ids, extractor=extractor)
    relevance.fit(ids)
    assert np.allclose(relevance.score_audio(clips[2], SR, ids), relevance.score_ids("c2", ids))
