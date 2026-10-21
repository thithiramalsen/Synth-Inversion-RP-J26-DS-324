"""Audio feature summaries for relevance (Phase 6).

Both representations come from ONE short-time power spectrum per clip, computed exactly as the
legacy pilot_v1 prototype does (``c3_recommendation/pipeline.py:extract_mfcc_summary``) so that
``mfcc26`` is continuous with the prototype:

* frames: reflect-pad n_fft/2, n_fft = 2048, hop = 512, symmetric Hann (``np.hanning``)
* power:  |rfft|^2 scaled by (sum(window) / 2)^2
* mel:    triangular HTK-mel filters (unnormalised) between f_min and f_max
* log:    natural log of max(mel power, 1e-12)

``mfcc26``       - 40 mel bands -> orthonormal DCT-II -> 13 MFCCs -> mean + std over frames (26)
``logmel_stats`` - 64 mel bands, log power -> mean + std over frames (128)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

REPRESENTATIONS = ("mfcc26", "logmel_stats")


@dataclass(frozen=True)
class FeatureSettings:
    sample_rate: int = 44100
    n_fft: int = 2048
    hop_length: int = 512
    f_min_hz: float = 20.0
    f_max_hz: float = 20000.0
    mfcc_n_mels: int = 40
    n_mfcc: int = 13
    logmel_n_mels: int = 64
    log_floor: float = 1e-12
    window: str = "symmetric Hann (np.hanning)"
    frame_padding: str = "reflect, n_fft // 2 each side"
    summary: str = "per-dimension mean and population std over frames"

    def as_dict(self) -> dict:
        return asdict(self)

    def dims(self, representation: str) -> int:
        if representation == "mfcc26":
            return 2 * self.n_mfcc
        if representation == "logmel_stats":
            return 2 * self.logmel_n_mels
        raise ValueError(f"unknown representation {representation!r}")


def hz_to_mel(frequency_hz):
    return 2595.0 * np.log10(1.0 + np.asarray(frequency_hz) / 700.0)


def mel_to_hz(mel):
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def mel_filterbank(sample_rate: int, n_fft: int, n_mels: int, f_min_hz: float, f_max_hz: float) -> np.ndarray:
    if not 0.0 <= f_min_hz < f_max_hz <= sample_rate / 2.0:
        raise ValueError("mel frequency limits must be inside the Nyquist interval")
    frequencies = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    points_hz = mel_to_hz(np.linspace(hz_to_mel(f_min_hz), hz_to_mel(f_max_hz), n_mels + 2))
    bank = np.zeros((n_mels, len(frequencies)), dtype=np.float64)
    for index in range(n_mels):
        left, center, right = points_hz[index : index + 3]
        rising = (frequencies - left) / max(center - left, np.finfo(float).eps)
        falling = (right - frequencies) / max(right - center, np.finfo(float).eps)
        bank[index] = np.maximum(0.0, np.minimum(rising, falling))
    if np.any(bank.sum(axis=1) == 0.0):
        raise ValueError("at least one mel filter is empty")
    return bank


def dct_basis(n_mfcc: int, n_mels: int) -> np.ndarray:
    """Orthonormal DCT-II rows."""
    mel_indexes = np.arange(n_mels, dtype=np.float64)
    coefficient_indexes = np.arange(n_mfcc, dtype=np.float64)[:, None]
    basis = np.cos(np.pi / n_mels * (mel_indexes + 0.5) * coefficient_indexes)
    basis[0] *= math.sqrt(1.0 / n_mels)
    basis[1:] *= math.sqrt(2.0 / n_mels)
    return basis


class FeatureExtractor:
    """Computes every representation from one power spectrum per clip."""

    def __init__(self, settings: FeatureSettings = FeatureSettings()):
        s = self.settings = settings
        self.window = np.hanning(s.n_fft)
        self.power_scale = max(self.window.sum() / 2.0, np.finfo(float).eps)
        self.mfcc_bank = mel_filterbank(s.sample_rate, s.n_fft, s.mfcc_n_mels, s.f_min_hz, s.f_max_hz)
        self.dct = dct_basis(s.n_mfcc, s.mfcc_n_mels)
        self.logmel_bank = mel_filterbank(s.sample_rate, s.n_fft, s.logmel_n_mels, s.f_min_hz, s.f_max_hz)

    def power_spectrum(self, audio: np.ndarray) -> np.ndarray:
        n_fft, hop = self.settings.n_fft, self.settings.hop_length
        audio = np.asarray(audio, dtype=np.float64)
        if audio.ndim != 1 or len(audio) < 2:
            raise ValueError("expected mono audio with at least 2 samples")
        padded = np.pad(audio, n_fft // 2, mode="reflect")
        if len(padded) < n_fft:
            padded = np.pad(padded, (0, n_fft - len(padded)))
        frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop]
        spectrum = np.fft.rfft(frames * self.window, n=n_fft, axis=1)
        return np.square(np.abs(spectrum) / self.power_scale)
    
#sound fingerprint - one spectrum per sounds give both fingerprint ,MFCC 26 is the exact pilott formula"""
    def extract(self, audio: np.ndarray, sample_rate: int) -> dict[str, np.ndarray]:
        if sample_rate != self.settings.sample_rate:
            raise ValueError(f"expected {self.settings.sample_rate} Hz audio, got {sample_rate}")
        power = self.power_spectrum(audio)
        floor = self.settings.log_floor
        mfcc = np.log(np.maximum(power @ self.mfcc_bank.T, floor)) @ self.dct.T
        logmel = np.log(np.maximum(power @ self.logmel_bank.T, floor))
        return {
            "mfcc26": np.concatenate((mfcc.mean(axis=0), mfcc.std(axis=0))),
            "logmel_stats": np.concatenate((logmel.mean(axis=0), logmel.std(axis=0))),
        }


# ---------------------------------------------------------------------- parallel extraction
_WORKER: dict = {}


def _init_worker(corpus_dir: str, settings: FeatureSettings) -> None:
    from .audio_io import CorpusAudioReader

    _WORKER["reader"] = CorpusAudioReader(corpus_dir)
    _WORKER["extractor"] = FeatureExtractor(settings)


def _extract_ids(sample_ids: list[str]) -> dict[str, np.ndarray]:
    """Worker task: features for a chunk of IDs, rows in the given order."""
    reader, extractor = _WORKER["reader"], _WORKER["extractor"]
    out = {rep: np.empty((len(sample_ids), extractor.settings.dims(rep))) for rep in REPRESENTATIONS}
    for row, sample_id in enumerate(sample_ids):
        audio, sr = reader.load(sample_id)
        for rep, vector in extractor.extract(audio, sr).items():
            out[rep][row] = vector
    return out


def extract_corpus(corpus_dir, sample_ids, settings: FeatureSettings = FeatureSettings(), workers: int = 1,
                   chunk: int = 256, progress=None) -> dict[str, np.ndarray]:
    """Stream the corpus once (rule R8) and return ``{representation: (n, dims) array}`` in ID order.

    Workers each hold one reader + extractor; only ``chunk`` clips are in memory per worker.
    """
    sample_ids = list(sample_ids)
    out = {rep: np.empty((len(sample_ids), settings.dims(rep))) for rep in REPRESENTATIONS}
    chunks = [sample_ids[i : i + chunk] for i in range(0, len(sample_ids), chunk)]
    done = 0
    if workers <= 1:
        _init_worker(str(corpus_dir), settings)
        results = map(_extract_ids, chunks)
        for start, part in zip(range(0, len(sample_ids), chunk), results):
            for rep in REPRESENTATIONS:
                out[rep][start : start + len(part[rep])] = part[rep]
            done += len(part[REPRESENTATIONS[0]])
            if progress:
                progress(done, len(sample_ids))
        return out

    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                             initargs=(str(corpus_dir), settings)) as pool:
        for start, part in zip(range(0, len(sample_ids), chunk), pool.map(_extract_ids, chunks)):
            for rep in REPRESENTATIONS:
                out[rep][start : start + len(part[rep])] = part[rep]
            done += len(part[REPRESENTATIONS[0]])
            if progress:
                progress(done, len(sample_ids))
    return out


# ---------------------------------------------------------------------- cache
FEATURE_META = "features_meta.json"
FEATURE_INDEX = "feature_index.parquet"


def load_feature_cache(features_dir, representation: str):
    """Return ``(array, sample_ids, meta)`` for a cached representation; checks shape and settings."""
    import json
    from pathlib import Path

    import pandas as pd

    features_dir = Path(features_dir)
    meta = json.loads((features_dir / FEATURE_META).read_text(encoding="utf-8"))
    if representation not in meta["representations"]:
        raise KeyError(f"{representation!r} not in feature cache {features_dir}")
    array = np.load(features_dir / meta["representations"][representation]["file"])
    ids = pd.read_parquet(features_dir / FEATURE_INDEX)["sample_id"].tolist()
    if array.shape != (len(ids), meta["representations"][representation]["dims"]):
        raise ValueError(f"{representation}: cache shape {array.shape} does not match its index/meta")
    return array, ids, meta
