"""Audio reader on a tiny synthetic corpus: DC-on-read, float32 policy, batching, external clips."""

import json

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import sosfilt

from c3.audio_io import (
    AudioPolicy, CorpusAudioReader, canonical_float32, generation_running, load_external_audio, sample_digest,
)

from conftest import hold_generator_lock

SR = 44100
N = 441  # 0.01 s keeps fixtures tiny
SOS = [[0.9989930508651772, -1.9979861017303544, 0.9989930508651772, 1.0, -1.9979850877835377, 0.9979871156771719]]


def make_recipe(**overrides) -> dict:
    recipe = {
        "storage_policy": "raw_float_dc_on_read_v1",
        "processed_float32_policy": "float32_subnormal_signed_zero_v1",
        "synthesis": {
            "audio_policy_id": "dc_highpass_10hz_v1",
            "sample_rate": SR,
            "channels": 1,
            "render_duration_seconds": N / SR,
            "audio_processing": {"policy": {
                "filter": {"implementation": "scipy.signal.sosfilt", "sos": SOS},
                "application": {"passes": 1, "normalization": "none", "additional_gain": 1.0},
            }},
        },
    }
    recipe.update(overrides)
    return recipe


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "raw_float").mkdir()
    (tmp_path / "recipe.json").write_text(json.dumps(make_recipe()))
    rng = np.random.default_rng(0)
    clips = {}
    for i in range(5):
        sid = f"s_{i:05d}"
        clips[sid] = (0.3 * rng.standard_normal(N) + 0.01).astype(np.float32)  # with DC offset
        sf.write(tmp_path / "raw_float" / f"{sid}.wav", clips[sid], SR, subtype="FLOAT")
    return tmp_path, clips


def test_load_applies_dc_filter_once_and_float32_policy(corpus):
    path, clips = corpus
    audio, sr = CorpusAudioReader(path).load("s_00000")
    expected = canonical_float32(sosfilt(np.asarray(SOS), clips["s_00000"].astype(np.float64)))
    assert sr == SR and audio.dtype == np.dtype("<f4") and audio.shape == (N,)
    assert sample_digest(audio) == sample_digest(expected)
    assert abs(audio.mean()) < abs(clips["s_00000"].mean())


def test_iter_batches_is_bounded_and_ordered(corpus):
    path, _ = corpus
    reader = CorpusAudioReader(path)
    ids = [f"s_{i:05d}" for i in range(5)]
    batches = list(reader.iter_batches(ids, batch=2))
    assert [b[0] for b in batches] == [ids[0:2], ids[2:4], ids[4:5]]
    assert batches[0][1].shape == (2, N)
    assert np.array_equal(batches[1][1][1], reader.load("s_00003")[0])


def test_wrong_master_format_rejected(corpus):
    path, _ = corpus
    sf.write(path / "raw_float" / "bad.wav", np.zeros(N, np.float32), 22050, subtype="FLOAT")
    with pytest.raises(ValueError, match="unexpected master format"):
        CorpusAudioReader(path).read_raw("bad")


def test_unknown_policy_rejected():
    with pytest.raises(ValueError, match="storage policy"):
        AudioPolicy(make_recipe(storage_policy="something_else"))


def test_canonical_float32_zeroes_subnormals_keeping_sign():
    tiny = np.array([1e-40, -1e-40, 0.5, -0.0], dtype=np.float32)
    out = canonical_float32(tiny)
    assert out[0] == 0 and not np.signbit(out[0])
    assert out[1] == 0 and np.signbit(out[1])
    assert out[2] == np.float32(0.5) and np.signbit(out[3])


def test_generation_running_uses_os_lock_not_file_presence(tmp_path):
    assert generation_running(tmp_path) is False
    (tmp_path / ".run.lock").write_bytes(b"0")
    assert generation_running(tmp_path) is False
    with hold_generator_lock(tmp_path):
        assert generation_running(tmp_path) is True
    assert generation_running(tmp_path) is False


def test_external_audio_downmixed_resampled_and_padded(tmp_path):
    policy = AudioPolicy(make_recipe())
    stereo = np.random.default_rng(1).standard_normal((100, 2)) * 0.1
    sf.write(tmp_path / "q.wav", stereo, 22050)
    audio, sr = load_external_audio(tmp_path / "q.wav", policy)
    assert sr == SR and audio.shape == (N,) and audio.dtype == np.dtype("<f4")
    # 100 frames at 22.05 kHz -> 200 at 44.1 kHz, then zero padding; after the DC high-pass the
    # padded tail holds only the IIR filter's small decaying response, not the signal.
    tail, head = np.abs(audio[250:]), np.abs(audio[:200])
    assert tail.max() < 0.1 * head.max()
    assert np.all(np.diff(tail) <= 0)

    long = np.random.default_rng(2).standard_normal(5 * N) * 0.1
    sf.write(tmp_path / "long.wav", long, SR)
    assert load_external_audio(tmp_path / "long.wav", policy)[0].shape == (N,)
