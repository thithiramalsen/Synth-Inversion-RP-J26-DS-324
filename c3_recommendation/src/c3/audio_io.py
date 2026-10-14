"""Streaming audio reader for ``corpus_v4`` and external-query loading.

The corpus stores one raw (unconditioned) 32-bit FLOAT WAV per sample. Processed audio is
derived on read (storage policy ``raw_float_dc_on_read_v1``):

1. read the raw mono float32 master (44.1 kHz, 132,300 frames);
2. apply the ``dc_highpass_10hz_v1`` SOS filter once, in float64, zero initial state;
3. cast to little-endian float32 and zero subnormals keeping their sign
   (``float32_subnormal_signed_zero_v1``).

Everything is read from the corpus ``recipe.json``; the result is checked bit-exactly against
the ``processed_samples_sha256`` hashes recorded by the generator (Phase 5 gate).
Never load the whole corpus: use :meth:`CorpusAudioReader.iter_batches` (rule R8).
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, sosfilt

RUN_LOCK = ".run.lock"
EXPECTED_STORAGE_POLICY = "raw_float_dc_on_read_v1"
EXPECTED_FLOAT_POLICY = "float32_subnormal_signed_zero_v1"


# ---------------------------------------------------------------------- generator lock
@contextmanager
def _locked_probe(path: Path):
    """Try to take the generator's 1-byte OS lock without writing; yields True if it was free."""
    with path.open("rb") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def generation_running(corpus_dir: str | Path) -> bool:
    """True while a generator holds the OS lock on ``.run.lock``.

    The generator never deletes ``.run.lock``; it only locks it while writing
    (``generation/generate_corpus.py:exclusive_run``). File presence alone means nothing.
    """
    lock = Path(corpus_dir) / RUN_LOCK
    if not lock.exists():
        return False
    with _locked_probe(lock) as free:
        return not free


# ---------------------------------------------------------------------- sample helpers
def canonical_float32(audio: np.ndarray) -> np.ndarray:
    """Cast to little-endian float32 and zero subnormals, keeping the sign bit."""
    result = np.array(audio, dtype="<f4", copy=True)
    bits = result.view(np.uint32)
    subnormal = ((bits & 0x7F800000) == 0) & ((bits & 0x007FFFFF) != 0)
    bits[subnormal] &= np.uint32(0x80000000)
    return result


def sample_digest(audio: np.ndarray) -> str:
    """SHA-256 of little-endian float32 samples (the generator's hash format)."""
    return hashlib.sha256(np.asarray(audio, dtype="<f4").tobytes()).hexdigest()


class AudioPolicy:
    """Rendering format and DC policy, read from the corpus ``recipe.json``."""

    def __init__(self, recipe: dict):
        synthesis = recipe["synthesis"]
        policy = synthesis["audio_processing"]["policy"]
        self.storage_policy = recipe.get("storage_policy")
        self.float_policy = recipe.get("processed_float32_policy")
        if self.storage_policy != EXPECTED_STORAGE_POLICY:
            raise ValueError(f"unsupported storage policy {self.storage_policy!r}")
        if self.float_policy != EXPECTED_FLOAT_POLICY:
            raise ValueError(f"unsupported processed float policy {self.float_policy!r}")
        self.policy_id = synthesis["audio_policy_id"]
        self.sample_rate = int(synthesis["sample_rate"])
        self.channels = int(synthesis["channels"])
        self.n_samples = int(round(synthesis["render_duration_seconds"] * self.sample_rate))
        flt = policy["filter"]
        if flt["implementation"] != "scipy.signal.sosfilt" or policy["application"]["passes"] != 1:
            raise ValueError("unexpected DC filter definition in recipe")
        if policy["application"]["normalization"] != "none" or policy["application"]["additional_gain"] != 1.0:
            raise ValueError("recipe declares normalisation/gain; reader does not implement it")
        self.sos = np.asarray(flt["sos"], dtype=np.float64)

    @classmethod
    def from_corpus(cls, corpus_dir: str | Path) -> "AudioPolicy":
        return cls(json.loads((Path(corpus_dir) / "recipe.json").read_text(encoding="utf-8")))

    def process(self, raw: np.ndarray) -> np.ndarray:
        """Raw float master -> canonical DC-conditioned float32 (applied exactly once)."""
        raw = np.asarray(raw, dtype=np.float64)
        if raw.ndim != 1 or not np.isfinite(raw).all():
            raise ValueError("expected finite mono audio")
        return canonical_float32(sosfilt(self.sos, raw))

    def describe(self) -> dict:
        return {"policy_id": self.policy_id, "storage_policy": self.storage_policy,
                "float_policy": self.float_policy, "sample_rate": self.sample_rate,
                "channels": self.channels, "n_samples": self.n_samples, "sos": self.sos.tolist()}


# ---------------------------------------------------------------------- corpus reader
class CorpusAudioReader:
    """Read processed corpus audio one sample or one bounded batch at a time."""

    def __init__(self, corpus_dir: str | Path, policy: AudioPolicy | None = None):
        self.corpus_dir = Path(corpus_dir)
        self.policy = policy or AudioPolicy.from_corpus(self.corpus_dir)

    def raw_path(self, sample_id: str) -> Path:
        return self.corpus_dir / "raw_float" / f"{sample_id}.wav"

    def read_raw(self, sample_id: str) -> np.ndarray:
        path = self.raw_path(sample_id)
        info = sf.info(path)
        if (info.subtype != "FLOAT" or info.channels != self.policy.channels
                or info.samplerate != self.policy.sample_rate or info.frames != self.policy.n_samples):
            raise ValueError(f"unexpected master format: {path}")
        return sf.read(path, dtype="float32")[0]

    def load(self, sample_id: str) -> tuple[np.ndarray, int]:
        return self.policy.process(self.read_raw(sample_id)), self.policy.sample_rate

    def iter_batches(self, sample_ids: Sequence[str], batch: int = 64) -> Iterator[tuple[list[str], np.ndarray]]:
        """Yield ``(ids, array[len(ids), n_samples])``; memory is ``batch`` clips at a time."""
        if batch < 1:
            raise ValueError("batch must be positive")
        ids = list(sample_ids)
        for start in range(0, len(ids), batch):
            chunk = ids[start : start + batch]
            out = np.empty((len(chunk), self.policy.n_samples), dtype=np.float32)
            for row, sample_id in enumerate(chunk):
                out[row] = self.load(sample_id)[0]
            yield chunk, out


# ---------------------------------------------------------------------- external queries
def load_external_audio(path: str | Path, policy: AudioPolicy) -> tuple[np.ndarray, int]:
    """Prepare an external clip like a corpus sample.

    Downmix to mono (channel mean), resample to the corpus rate with ``scipy.signal.resample_poly``,
    trim or zero-pad at the end to the corpus length, then apply the same DC policy the corpus
    uses. No peak/loudness normalisation, because the corpus is not normalised.
    """
    audio, sr = sf.read(Path(path), dtype="float64", always_2d=True)
    mono = audio.mean(axis=1)
    if sr != policy.sample_rate:
        g = np.gcd(int(sr), policy.sample_rate)
        mono = resample_poly(mono, policy.sample_rate // g, int(sr) // g)
    if len(mono) >= policy.n_samples:
        mono = mono[: policy.n_samples]
    else:
        mono = np.pad(mono, (0, policy.n_samples - len(mono)))
    return policy.process(mono), policy.sample_rate
