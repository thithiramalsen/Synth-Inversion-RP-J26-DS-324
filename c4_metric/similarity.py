"""Frozen C4 similarity baselines with one score convention.

All returned ``similarity`` values use higher = more similar. ``distance`` is
the corresponding lower-is-better quantity. MFCC and STFT use cosine similarity
between level-conditioned, duration-pooled feature summaries. CLAP uses cosine
similarity between frozen audio embeddings. The synth-aware baseline uses known
normalized Vital control settings and is available only for corpus sample IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_MANIFEST = ROOT / "data/raw/corpus_v4/manifest.csv"
TARGET_RATE = 44_100
N_FFT = 2048
HOP = 512
N_MELS = 40
N_MFCC = 13
TARGET_RMS = 0.03
STFT_SCALES = (512, 1024, 2048, 4096)


@dataclass(frozen=True)
class SimilarityResult:
    method: str
    similarity: float
    distance: float
    convention: str = "higher similarity is better; lower distance is better"


def _mono(audio: np.ndarray) -> np.ndarray:
    value = np.asarray(audio, dtype=np.float64)
    if value.ndim == 2:
        if value.shape[0] <= 8 and value.shape[1] > value.shape[0]:
            value = value.mean(axis=0)
        else:
            value = value.mean(axis=1)
    if value.ndim != 1 or value.size == 0 or not np.isfinite(value).all():
        raise ValueError("Audio must be a nonempty finite waveform")
    return value


def prepare_audio(source: Any, sample_rate: int | None = None) -> np.ndarray:
    """Load/downmix/resample, DC-condition and level-match one audio source.

    ``source`` can be a path, an ndarray (with ``sample_rate``), or a
    ``(waveform, sample_rate)`` pair. The returned waveform is mono float64 at
    44.1 kHz. Per-clip RMS is normalized to a fixed target with a peak ceiling;
    this limits loudness as a decision cue while preserving dynamics within a
    clip. Duration is retained; feature pooling handles duration differences.
    """
    if isinstance(source, tuple) and len(source) == 2:
        source, sample_rate = source
    if isinstance(source, (str, Path)):
        audio, actual_rate = sf.read(str(source), dtype="float64", always_2d=True)
        audio = audio.mean(axis=1)
        sample_rate = int(actual_rate)
    else:
        audio = _mono(np.asarray(source))
    if sample_rate is None or int(sample_rate) <= 0:
        raise ValueError("A positive sample rate is required for array audio")
    sample_rate = int(sample_rate)
    audio = _mono(audio)
    if sample_rate != TARGET_RATE:
        from math import gcd
        divisor = gcd(TARGET_RATE, sample_rate)
        audio = resample_poly(audio, TARGET_RATE // divisor, sample_rate // divisor)
    from generation.audio_processing import dc_filter
    audio = dc_filter(audio, TARGET_RATE)
    rms = float(np.sqrt(np.mean(audio * audio)))
    peak = float(np.max(np.abs(audio)))
    if not np.isfinite(rms) or rms < 1e-10 or peak < 1e-10:
        raise ValueError("Audio is silent or too quiet to score")
    gain = min(TARGET_RMS / rms, 0.89 / peak)
    return (audio * gain).astype(np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-12:
        return 1.0 if np.allclose(a, b) else 0.0
    return float(np.clip(np.dot(a, b) / denom, -1.0, 1.0))


def _frames(audio: np.ndarray, n_fft: int = N_FFT, hop: int = HOP) -> np.ndarray:
    if len(audio) < n_fft:
        audio = np.pad(audio, (0, n_fft - len(audio)))
    remainder = (len(audio) - n_fft) % hop
    if remainder:
        audio = np.pad(audio, (0, hop - remainder))
    shape = (1 + (len(audio) - n_fft) // hop, n_fft)
    strides = (audio.strides[0] * hop, audio.strides[0])
    return np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides).copy()


def _hz_to_mel(value: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + value / 700.0)


def _mel_to_hz(value: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (value / 2595.0) - 1.0)


def _mel_bank() -> np.ndarray:
    frequencies = np.linspace(0.0, TARGET_RATE / 2, N_FFT // 2 + 1)
    hz_points = _mel_to_hz(np.linspace(_hz_to_mel(np.array([0.0]))[0],
                                       _hz_to_mel(np.array([TARGET_RATE / 2]))[0],
                                       N_MELS + 2))
    bank = np.zeros((N_MELS, len(frequencies)), dtype=np.float64)
    for i in range(N_MELS):
        left, center, right = hz_points[i:i + 3]
        bank[i] = np.maximum(0.0, np.minimum(
            (frequencies - left) / max(center - left, 1e-12),
            (right - frequencies) / max(right - center, 1e-12)))
    return bank


def _mfcc_summary(audio: np.ndarray) -> np.ndarray:
    framed = _frames(audio) * np.hanning(N_FFT)
    power = np.abs(np.fft.rfft(framed, axis=1)) ** 2
    log_mel = np.log(np.maximum(power @ _mel_bank().T, 1e-10))
    bins = np.arange(N_MELS)
    basis = np.cos(np.pi / N_MELS * (bins[None, :] + 0.5) * np.arange(N_MFCC)[:, None])
    coefficients = log_mel @ basis.T
    # Omit C0, which primarily tracks overall energy after conditioning.
    content = coefficients[:, 1:]
    return np.concatenate([content.mean(axis=0), content.std(axis=0)])


def _stft_summary(audio: np.ndarray, n_fft: int = N_FFT) -> np.ndarray:
    framed = _frames(audio, n_fft, max(1, n_fft // 4)) * np.hanning(n_fft)
    magnitude = np.abs(np.fft.rfft(framed, axis=1))
    # Average a unit-L1 spectrum per frame; log scaling limits dominant peaks.
    magnitude /= np.maximum(magnitude.sum(axis=1, keepdims=True), 1e-12)
    profile = magnitude.mean(axis=0)
    return np.log(np.maximum(profile, 1e-10))


def _multiscale_stft_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Average normalized-spectrum cosine over four Hann STFT resolutions."""
    scale_similarities = [_cosine(_stft_summary(a, scale), _stft_summary(b, scale))
                          for scale in STFT_SCALES]
    return float((np.mean(scale_similarities) + 1.0) / 2.0)


@lru_cache(maxsize=1)
def _cdpam_model():
    """Load the optional published CDPAM package once, or explain how to enable it."""
    try:
        import cdpam
        import torch
    except ImportError as error:
        raise RuntimeError("CDPAM is optional and is not installed; install cdpam and its requirements") from error
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = cdpam.CDPAM(dev=device)
    if hasattr(model, "eval"):
        model.eval()
    return cdpam, torch, model, device


def _cdpam_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Compute the official CDPAM pair distance from canonicalized waveforms.

    CDPAM's published pretrained models expect 22.05 kHz 16-bit PCM inputs;
    temporary PCM files route data through the package's own audio loader.
    """
    import tempfile
    from scipy.io import wavfile

    cdpam, torch, model, device = _cdpam_model()
    paths = []
    try:
        for waveform in (a, b):
            resampled = resample_poly(waveform, 1, 2)
            pcm = np.round(np.clip(resampled, -1.0, 1.0) * 32767.0).astype(np.int16)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                paths.append(Path(handle.name))
            wavfile.write(paths[-1], 22_050, pcm)
        reference = cdpam.load_audio(str(paths[0]))
        candidate = cdpam.load_audio(str(paths[1]))
        if hasattr(reference, "to"):
            reference = reference.to(device)
        else:
            reference = torch.as_tensor(reference, device=device)
        if hasattr(candidate, "to"):
            candidate = candidate.to(device)
        else:
            candidate = torch.as_tensor(candidate, device=device)
        with torch.inference_mode():
            value = model.forward(reference, candidate)
        distance = float(np.asarray(value.detach().cpu() if hasattr(value, "detach") else value).reshape(-1)[0])
        if not np.isfinite(distance):
            raise ValueError("CDPAM returned a non-finite distance")
        return distance
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


@lru_cache(maxsize=4)
def _clap_model(model_id: str, revision: str | None, local_files_only: bool = False):
    try:
        import torch
        from transformers import ClapAudioModelWithProjection, ClapProcessor
    except ImportError as error:
        raise RuntimeError("CLAP scoring requires torch and transformers") from error
    processor = ClapProcessor.from_pretrained(model_id, revision=revision,
                                               local_files_only=local_files_only)
    model = ClapAudioModelWithProjection.from_pretrained(model_id, revision=revision,
                                                          local_files_only=local_files_only)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    return torch, processor, model, device


def _clap_embeddings(a: np.ndarray, b: np.ndarray, model_id: str, revision: str | None,
                     local_files_only: bool = False) -> np.ndarray:
    torch, processor, model, device = _clap_model(model_id, revision, local_files_only)
    # HF CLAP expects 48 kHz. Audio has already been canonicalized to 44.1 kHz.
    waveforms = [resample_poly(x, 160, 147).astype(np.float32) for x in (a, b)]
    inputs = processor(audios=waveforms, sampling_rate=48_000, return_tensors="pt", padding=True)
    inputs = {key: value.to(device) for key, value in inputs.items()}
    with torch.inference_mode():
        embeddings = model(**inputs).audio_embeds.detach().cpu().numpy()
    return embeddings.astype(np.float64)


@lru_cache(maxsize=2)
def _parameter_table(manifest_text: str) -> dict[str, np.ndarray]:
    import csv
    manifest_path = Path(manifest_text)
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        names = sorted(k.removesuffix("_sample_01") for k in (reader.fieldnames or [])
                       if k.endswith("_sample_01"))
        if not names:
            raise ValueError("Manifest has no normalized *_sample_01 parameter columns")
        return {row["sample_id"]: np.asarray([float(row[f"{name}_sample_01"]) for name in names])
                for row in reader}


def _parameter_vectors(sample_ids: tuple[str, str], manifest_path: Path) -> tuple[np.ndarray, np.ndarray]:
    table = _parameter_table(str(manifest_path.resolve()))
    missing = set(sample_ids) - table.keys()
    if missing:
        raise ValueError(f"Sample IDs absent from synth-aware manifest: {sorted(missing)}")
    return table[sample_ids[0]], table[sample_ids[1]]


def score_similarity(reference_audio: Any, candidate_audio: Any, method: str = "mfcc", *,
                     sample_rate: int | None = None,
                     reference_id: str | None = None, candidate_id: str | None = None,
                     manifest_path: Path = DEFAULT_MANIFEST,
                     clap_model: str = "laion/clap-htsat-unfused",
                     clap_revision: str | None = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a",
                     clap_local_files_only: bool = False) -> SimilarityResult:
    """Score one reference/candidate pair. Every method ranks higher = closer.

    Methods: ``mfcc``, ``stft``, ``ms_stft``, ``clap``, ``cdpam``, and ``synth_aware``. The latter uses
    normalized synth controls and needs both sample IDs. ``cdpam`` raises a clear
    unavailable error unless a genuine implementation is integrated.
    """
    method = method.casefold()
    if method == "synth_aware":
        if not reference_id or not candidate_id:
            raise ValueError("synth_aware requires reference_id and candidate_id")
        a, b = _parameter_vectors((reference_id, candidate_id), manifest_path)
        distance = float(np.linalg.norm(a - b) / np.sqrt(a.size))
        return SimilarityResult(method, float(np.clip(1.0 - distance, 0.0, 1.0)), distance)
    if method == "cdpam":
        a = prepare_audio(reference_audio, sample_rate)
        b = prepare_audio(candidate_audio, sample_rate)
        distance = _cdpam_distance(a, b)
        return SimilarityResult(method, -distance, distance)
    if method not in {"mfcc", "stft", "ms_stft", "clap"}:
        raise ValueError(f"Unknown similarity method: {method}")
    a = prepare_audio(reference_audio, sample_rate)
    b = prepare_audio(candidate_audio, sample_rate)
    if method == "mfcc":
        raw = _cosine(_mfcc_summary(a), _mfcc_summary(b))
        similarity = (raw + 1.0) / 2.0
    elif method == "stft":
        raw = _cosine(_stft_summary(a), _stft_summary(b))
        similarity = (raw + 1.0) / 2.0
    elif method == "ms_stft":
        similarity = _multiscale_stft_similarity(a, b)
    else:
        embeddings = _clap_embeddings(a, b, clap_model, clap_revision, clap_local_files_only)
        raw = _cosine(embeddings[0], embeddings[1])
        similarity = raw
    similarity = float(np.clip(similarity, -1.0 if method == "clap" else 0.0, 1.0))
    return SimilarityResult(method, similarity, 1.0 - similarity)


def rank_candidates(reference_audio: Any, candidates: list[Any], method: str = "mfcc", **kwargs):
    """Return candidate scores sorted most-to-least similar."""
    scored = [(candidate, score_similarity(reference_audio, candidate, method, **kwargs))
              for candidate in candidates]
    return sorted(scored, key=lambda item: item[1].similarity, reverse=True)


def baseline_availability() -> dict[str, dict[str, str]]:
    return {
        "mfcc": {"status": "implemented", "score_direction": "higher similarity is better"},
        "stft": {"status": "implemented", "score_direction": "higher similarity is better"},
        "ms_stft": {"status": "implemented; mean cosine over 512/1024/2048/4096-point STFT summaries",
                    "score_direction": "higher similarity is better"},
        "clap": {"status": "implemented; requires cached/downloadable HF checkpoint",
                 "score_direction": "higher cosine similarity is better"},
        "cdpam": {"status": "optional published model; requires the cdpam package and its checkpoint",
                  "score_direction": "lower perceptual distance is better"},
        "synth_aware": {"status": "implemented for samples with normalized synth metadata",
                        "score_direction": "higher parameter similarity is better"},
    }
