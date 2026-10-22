"""C1 feature set v2: energy-gated, level-invariant audio descriptors.

Replaces the historical baseline's unweighted frame means, which let near-silent
frames and quantization-level spectral bins dominate centroid/MFCC summaries.
Rules (versioned as FEATURE_VERSION):

* Spectral frames more than FRAME_GATE_DB below the loudest frame are ignored;
  bins more than BIN_FLOOR_DB below their frame's peak bin are zeroed; frame
  summaries are averaged with frame-energy weights.
* Every feature is invariant to a constant gain, so DC-conditioned corpus masters
  and level-matched study playback give comparable values.
* Temporal features use a 10 ms RMS envelope and fixed windows tied to the
  render protocol (1.5 s note hold, 3 s render).
* Quiet tails are summarized explicitly (tail level, release time), not deleted.

Input must already be processed by the declared audio policy; this module never
filters or normalizes.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

FEATURE_VERSION = "c1_features_v2"
SR = 44100
N_FFT, HOP = 2048, 512
FRAME_GATE_DB = 50.0
BIN_FLOOR_DB = 60.0
NOTE_OFF_S = 1.5
# Floors keep quantization-level energy from varying a feature (checked FLOAT vs PCM16).
HF_FLOOR_DB = -60.0
TAIL_FLOOR_DB = -60.0

FEATURE_NAMES = [
    # spectral
    "log2_centroid", "centroid_sd_oct", "early_minus_body_centroid_oct", "log2_rolloff85",
    "hf_energy_db", "lf_energy_fraction", "spectral_flatness_db", "spectral_flux",
    # temporal
    "log_attack_s", "log_peak_time_s", "held_drop_db", "decay_slope_db_s", "tail_rel_db",
    "release_time_s", "temporal_centroid_s", "early_energy_fraction", "tail_energy_fraction",
    # modulation / roughness
    "log_am_rough_15_150", "log_am_fluct_4_15",
]

_SOS_LP300 = signal.butter(4, 300, "low", fs=SR, output="sos")
_SOS_ROUGH = signal.butter(2, [15, 150], "bandpass", fs=1000, output="sos")
_SOS_FLUCT = signal.butter(2, [4, 15], "bandpass", fs=1000, output="sos")
_FREQS = np.fft.rfftfreq(N_FFT, 1 / SR)
_WINDOW = signal.get_window("hann", N_FFT)


def _db(x):
    return 10 * np.log10(np.maximum(x, 1e-30))


def _spectral(audio):
    frames = np.lib.stride_tricks.sliding_window_view(audio, N_FFT)[::HOP]
    power = np.abs(np.fft.rfft(frames * _WINDOW, axis=1)) ** 2  # (frames, bins)
    times = (np.arange(len(frames)) * HOP + N_FFT / 2) / SR
    energy = power.sum(axis=1)
    keep = _db(energy) > _db(energy.max()) - FRAME_GATE_DB
    p, t, e = power[keep], times[keep], energy[keep]
    p = np.where(p >= p.max(axis=1, keepdims=True) * 10 ** (-BIN_FLOOR_DB / 10), p, 0.0)
    w = e / e.sum()
    total = np.maximum(p.sum(axis=1), 1e-30)
    log_c = np.log2(np.maximum((p @ _FREQS) / total, 20.0))
    mean_c = float(w @ log_c)
    sd_c = float(np.sqrt(w @ (log_c - mean_c) ** 2))
    cum = np.cumsum(p, axis=1) / total[:, None]
    rolloff = _FREQS[np.argmax(cum >= 0.85, axis=1)]
    floor = p.max(axis=1, keepdims=True) * 10 ** (-BIN_FLOOR_DB / 10)
    pf = np.maximum(p, floor)[:, _FREQS >= 40]
    flat = _db(np.exp(np.log(pf).mean(axis=1)) / pf.mean(axis=1))
    norm = p / total[:, None]
    flux = np.r_[0.0, np.sqrt((np.diff(np.sqrt(norm), axis=0) ** 2).sum(axis=1))]

    def window_centroid(a, b):
        m = (t >= a) & (t < b)
        return float(np.average(log_c[m], weights=e[m])) if m.any() else mean_c

    pooled = (w[:, None] * norm).sum(axis=0)
    return dict(
        log2_centroid=mean_c, centroid_sd_oct=sd_c,
        early_minus_body_centroid_oct=window_centroid(0, 0.2) - window_centroid(0.4, 1.4),
        log2_rolloff85=float(w @ np.log2(np.maximum(rolloff, 20.0))),
        hf_energy_db=float(max(_db(pooled[_FREQS >= 2000].sum()), HF_FLOOR_DB)),
        lf_energy_fraction=float(pooled[_FREQS < 500].sum()),
        spectral_flatness_db=float(w @ flat), spectral_flux=float(w @ flux),
    )


def _temporal(audio):
    hop = SR // 100
    n = len(audio) // hop
    env = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    dt = hop / SR
    t = (np.arange(n) + 0.5) * dt
    env_db = 20 * np.log10(np.maximum(env, 1e-10))
    peak_i = int(np.argmax(env))
    peak, peak_db = env[peak_i], env_db[peak_i]
    above10 = np.flatnonzero(env[: peak_i + 1] >= 0.1 * peak)
    above90 = np.flatnonzero(env[: peak_i + 1] >= 0.9 * peak)
    attack = max((above90[0] - above10[0]) * dt, dt / 2)
    body = env_db[(t >= 0.4) & (t < 1.4)]
    held_db = float(np.median(body))
    seg = (t >= t[peak_i] + 0.05) & (t <= min(t[peak_i] + 0.5, NOTE_OFF_S))
    slope = float(np.polyfit(t[seg], env_db[seg], 1)[0]) if seg.sum() >= 5 else 0.0
    tail = env[(t >= 1.6) & (t < 2.4)]
    tail_db = 10 * np.log10(max(np.mean(tail ** 2), 1e-20))
    after = np.flatnonzero((t >= NOTE_OFF_S) & (env_db < env_db[int(NOTE_OFF_S / dt) - 1] - 40))
    release = float(t[after[0]] - NOTE_OFF_S) if len(after) else float(t[-1] - NOTE_OFF_S)
    energy = env ** 2
    seg_e = lambda a, b: energy[(t >= a) & (t < b)].sum()
    total = energy.sum()
    return dict(
        log_attack_s=float(np.log(attack)), log_peak_time_s=float(np.log(max(t[peak_i], dt / 2))),
        held_drop_db=float(np.clip(peak_db - held_db, 0, 80)), decay_slope_db_s=float(np.clip(slope, -300, 50)),
        tail_rel_db=float(np.clip(tail_db - peak_db, TAIL_FLOOR_DB, 0)), release_time_s=release,
        temporal_centroid_s=float((t * energy).sum() / total),
        early_energy_fraction=float(seg_e(0, 0.2) / total), tail_energy_fraction=float(seg_e(NOTE_OFF_S, 3.1) / total),
    )


def _modulation(audio):
    seg = audio[int(0.2 * SR): int(1.45 * SR)]
    env = signal.sosfiltfilt(_SOS_LP300, np.abs(signal.hilbert(seg)))[:: SR // 1000]
    mean = max(float(np.mean(env)), 1e-12)
    rough = signal.sosfiltfilt(_SOS_ROUGH, env)
    fluct = signal.sosfiltfilt(_SOS_FLUCT, env)
    return dict(log_am_rough_15_150=float(np.log(np.std(rough) / mean + 1e-4)),
                log_am_fluct_4_15=float(np.log(np.std(fluct) / mean + 1e-4)))


def extract(audio: np.ndarray, sr: int = SR) -> dict[str, float]:
    if sr != SR:
        raise ValueError("c1_features_v2 requires 44100 Hz audio")
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1 or not np.isfinite(audio).all() or np.max(np.abs(audio)) <= 0:
        raise ValueError("Expected finite, non-silent mono audio")
    out = {**_spectral(audio), **_temporal(audio), **_modulation(audio)}
    return {k: out[k] for k in FEATURE_NAMES}
