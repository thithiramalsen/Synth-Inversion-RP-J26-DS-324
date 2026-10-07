"""Versioned audio conditioning shared by rendering and study preparation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import sosfilt

ROOT = Path(__file__).resolve().parents[1]
DC_POLICY_ID = "dc_highpass_10hz_v1"
LEVEL_POLICY_ID = "held_rms_gain_v1"


def policy_definition() -> dict:
    path = ROOT / "generation/audio_policies" / f"{DC_POLICY_ID}.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    return {"policy": policy, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def mono_float(audio) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Expected nonempty, finite mono audio")
    return audio


def dc_filter(audio, sample_rate: int, *, input_policy_id: str = "raw") -> np.ndarray:
    if input_policy_id != "raw":
        raise ValueError("DC filtering requires raw input; refusing repeat processing")
    definition = policy_definition()["policy"]
    if sample_rate != definition["sample_rate_hz"]:
        raise ValueError("DC policy requires canonical 44100 Hz audio")
    return sosfilt(np.asarray(definition["filter"]["sos"]), mono_float(audio))


def audio_metrics(audio, sample_rate: int = 44100) -> dict:
    audio = mono_float(audio)
    rms = float(np.sqrt(np.mean(audio * audio)))
    mean = float(audio.mean())
    held = audio[:round(1.5 * sample_rate)]
    peak = float(np.max(np.abs(audio)))
    return dict(rms=rms, rms_dbfs=20 * np.log10(max(rms, 1e-15)), peak=peak,
                dc_offset=mean, dc_to_rms=abs(mean) / max(rms, 1e-15),
                held_rms=float(np.sqrt(np.mean(held * held))),
                tail_peak=float(np.max(np.abs(audio[-round(.05 * sample_rate):]))),
                clipped=peak >= 1., silent=rms < .001,
                dc_warning=abs(mean) >= .005 or abs(mean) / max(rms, 1e-15) >= .2)


def level_plan(metrics: list[dict], *, nominal_dbfs=-27., peak_ceiling=.89) -> dict:
    """Choose one held-note RMS target feasible for every selected clip."""
    if not metrics or any(m["held_rms"] <= 1e-8 for m in metrics):
        raise ValueError("Cannot level-match silent/empty audio")
    target = min(10 ** (nominal_dbfs / 20),
                 min(peak_ceiling * m["held_rms"] / max(m["peak"], 1e-15) for m in metrics))
    return dict(policy_id=LEVEL_POLICY_ID, window_seconds=[0., 1.5], nominal_dbfs=nominal_dbfs,
                target_rms=target, target_dbfs=20 * np.log10(target), peak_ceiling=peak_ceiling,
                method="constant gain per clip; no compression, fades or peak normalization",
                gains=[target / m["held_rms"] for m in metrics])


def apply_level(audio, gain: float, *, input_policy_id: str, peak_ceiling=.89) -> np.ndarray:
    if input_policy_id != DC_POLICY_ID:
        raise ValueError("Level matching requires DC-only audio; refusing missing/repeated processing")
    if not np.isfinite(gain) or gain <= 0:
        raise ValueError("Invalid gain")
    result = mono_float(audio) * gain
    if np.max(np.abs(result)) > peak_ceiling + 1e-8:
        raise ValueError("Level-matched audio exceeds peak ceiling")
    return result
