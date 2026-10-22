"""C4-side copy of C3's mfcc26 extraction contract, kept regression-tested."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SAMPLE_RATE = 44_100
N_FFT = 2048
HOP_LENGTH = 512
N_MELS = 40
N_MFCC = 13
F_MIN_HZ = 20.0
F_MAX_HZ = 20_000.0
FEATURE_DIMENSION = 26


def hz_to_mel(frequency_hz: np.ndarray | float) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + np.asarray(frequency_hz) / 700.0)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def mel_filterbank(sample_rate: int = SAMPLE_RATE, n_fft: int = N_FFT,
                   n_mels: int = N_MELS, f_min_hz: float = F_MIN_HZ,
                   f_max_hz: float = F_MAX_HZ) -> np.ndarray:
    if not 0.0 <= f_min_hz < f_max_hz <= sample_rate / 2.0:
        raise ValueError("MFCC frequency limits must be inside the Nyquist interval.")
    frequencies = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    points_hz = mel_to_hz(np.linspace(hz_to_mel(f_min_hz), hz_to_mel(f_max_hz), n_mels + 2))
    bank = np.zeros((n_mels, len(frequencies)), dtype=np.float64)
    for index in range(n_mels):
        left, center, right = points_hz[index:index + 3]
        rising = (frequencies - left) / max(center - left, np.finfo(float).eps)
        falling = (right - frequencies) / max(right - center, np.finfo(float).eps)
        bank[index] = np.maximum(0.0, np.minimum(rising, falling))
    if np.any(bank.sum(axis=1) == 0.0):
        raise ValueError("At least one mel filter is empty.")
    return bank


def dct_basis(n_mfcc: int = N_MFCC, n_mels: int = N_MELS) -> np.ndarray:
    mel_indexes = np.arange(n_mels, dtype=np.float64)
    coefficient_indexes = np.arange(n_mfcc, dtype=np.float64)[:, None]
    basis = np.cos(np.pi / n_mels * (mel_indexes + 0.5) * coefficient_indexes)
    basis[0] *= math.sqrt(1.0 / n_mels)
    basis[1:] *= math.sqrt(2.0 / n_mels)
    return basis


def read_target_audio(path: Path, target_sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    audio, sample_rate = sf.read(path, dtype="float64", always_2d=True)
    if len(audio) == 0:
        raise ValueError(f"Audio clip is empty: {path}")
    mono = audio.mean(axis=1)
    if sample_rate != target_sample_rate:
        divisor = math.gcd(sample_rate, target_sample_rate)
        mono = resample_poly(mono, target_sample_rate // divisor, sample_rate // divisor)
    return np.asarray(mono, dtype=np.float64)


def extract_mfcc_summary(audio: np.ndarray, settings: dict[str, Any],
                         bank: np.ndarray | None = None,
                         basis: np.ndarray | None = None) -> np.ndarray:
    """Return C3's 13 coefficient means followed by 13 standard deviations."""
    n_fft = int(settings["n_fft"])
    hop_length = int(settings["hop_length"])
    if len(audio) == 1:
        audio = np.pad(audio, (0, 1), mode="constant")
    pad_mode = "reflect" if len(audio) > 1 else "constant"
    padded = np.pad(audio, n_fft // 2, mode=pad_mode)
    if len(padded) < n_fft:
        padded = np.pad(padded, (0, n_fft - len(padded)))
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop_length]
    window = np.hanning(n_fft)
    spectrum = np.fft.rfft(frames * window, n=n_fft, axis=1)
    power = np.square(np.abs(spectrum) / max(window.sum() / 2.0, np.finfo(float).eps))
    if bank is None:
        bank = mel_filterbank(int(settings["sample_rate"]), n_fft, int(settings["n_mels"]),
                              float(settings["f_min_hz"]), float(settings["f_max_hz"]))
    if basis is None:
        basis = dct_basis(int(settings["n_mfcc"]), int(settings["n_mels"]))
    log_mel = np.log(np.maximum(power @ bank.T, 1e-12))
    mfcc = log_mel @ basis.T
    return np.concatenate((mfcc.mean(axis=0), mfcc.std(axis=0)))


__all__ = ["SAMPLE_RATE", "N_FFT", "HOP_LENGTH", "N_MELS", "N_MFCC", "F_MIN_HZ",
           "F_MAX_HZ", "FEATURE_DIMENSION", "dct_basis", "extract_mfcc_summary",
           "mel_filterbank", "read_target_audio"]
