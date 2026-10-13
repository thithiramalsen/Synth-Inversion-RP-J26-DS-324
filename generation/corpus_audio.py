"""Read single-master corpus rows as canonical DC-corrected FLOAT audio."""
from pathlib import Path
import hashlib
import numpy as np
import soundfile as sf
from generation.audio_processing import DC_POLICY_ID, dc_filter

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_FLOAT_POLICY = "float32_subnormal_signed_zero_v1"


def canonical_float32(audio):
    """Make float32 underflow independent of the renderer's CPU float mode.

    Vital rendering leaves flush-to-zero enabled in its worker. A fresh reader
    may preserve subnormal float32 values instead. Zero only those subnormals,
    retaining their sign, using bits so the current CPU float mode cannot affect
    the operation. Normal float32 samples and all raw masters remain untouched.
    """
    result = np.array(audio, dtype="<f4", copy=True)
    bits = result.view(np.uint32)
    subnormal = ((bits & 0x7f800000) == 0) & ((bits & 0x007fffff) != 0)
    bits[subnormal] &= np.uint32(0x80000000)
    return result


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
    processed = canonical_float32(dc_filter(raw, 44100))
    if verify:
        if sample_digest(raw) != row["raw_samples_sha256"]:
            raise ValueError(f"Raw waveform mismatch: {row['sample_id']}")
        if sample_digest(processed) != row["processed_samples_sha256"]:
            raise ValueError(f"Processed waveform mismatch: {row['sample_id']}")
    return processed, 44100
