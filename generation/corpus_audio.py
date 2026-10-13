"""Read single-master corpus rows as canonical DC-corrected FLOAT audio."""
from pathlib import Path
import hashlib
import numpy as np
import soundfile as sf
from generation.audio_processing import DC_POLICY_ID, dc_filter

ROOT = Path(__file__).resolve().parents[1]


def sample_digest(audio):
    """Hash canonical little-endian float32 samples, independent of WAV timestamps."""
    return hashlib.sha256(np.asarray(audio, dtype="<f4").tobytes()).hexdigest()


def raw_path(row, root=ROOT):
    path = (root / row["raw_audio_path"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Master path outside dataset project")
    return path


def read_raw(row, root=ROOT):
    path = raw_path(row, root)
    info = sf.info(path)
    if (info.subtype != "FLOAT" or info.channels != 1 or info.samplerate != 44100
            or info.frames != 132300):
        raise ValueError(f"Unexpected master format: {path}")
    return sf.read(path, dtype="float32")[0]


def load_audio(row, root=ROOT, *, verify=False):
    """Always apply DC once to RAW; cast as the historical processed FLOAT WAV did.

    Use this adapter before feature extraction/training instead of treating
    raw_audio_path as processed audio. No persistent second WAV is needed.
    """
    if row["audio_policy_id"] != DC_POLICY_ID:
        raise ValueError("Unexpected audio policy")
    raw = read_raw(row, root)
    processed = dc_filter(raw, 44100).astype(np.float32)
    if verify and (sample_digest(raw) != row["raw_samples_sha256"] or
                   sample_digest(processed) != row["processed_samples_sha256"]):
        raise ValueError(f"Waveform mismatch: {row['sample_id']}")
    return processed, 44100
