"""Small stable API for C3 or other callers to rank audio candidates."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import math

import numpy as np
from scipy.signal import resample_poly
import torch

from c4_metric.mfcc26 import (F_MAX_HZ, F_MIN_HZ, FEATURE_DIMENSION, HOP_LENGTH,
                              N_FFT, N_MELS, N_MFCC, SAMPLE_RATE, dct_basis,
                              extract_mfcc_summary, mel_filterbank, read_target_audio)
from c4_metric.model import TripletProjection, cosine_distance
from c4_metric.similarity import (SimilarityResult, _clap_embeddings, prepare_audio,
                                  rank_candidates, score_similarity)

SYNTHETIC_MARK = "SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"
PILOT_MARK = "REHEARSAL_PILOT_DO_NOT_USE_AS_VALIDATED_HUMAN_STUDY_RESULTS"
MFCC_ENCODER_ID = "c3-mfcc26"
MFCC_SETTINGS = {
    "sample_rate": SAMPLE_RATE, "n_fft": N_FFT, "hop_length": HOP_LENGTH,
    "n_mels": N_MELS, "n_mfcc": N_MFCC,
    "f_min_hz": F_MIN_HZ, "f_max_hz": F_MAX_HZ,
}


class MFCCAdaptedScorer:
    """C3 audio-input-compatible scorer for C4 checkpoints trained on mfcc26."""

    def __init__(self, checkpoint: Path, *, device: str | None = None,
                 allow_synthetic_checkpoint: bool = False,
                 allow_pilot_checkpoint: bool = False):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        state = torch.load(checkpoint, map_location=self.device, weights_only=True)
        if state.get("data_status") == SYNTHETIC_MARK and not allow_synthetic_checkpoint:
            raise ValueError("Refusing to use a synthetic-label checkpoint as a C3 perceptual scorer")
        if state.get("data_status") == PILOT_MARK and not allow_pilot_checkpoint:
            raise ValueError("Refusing to use a rehearsal pilot checkpoint without explicit opt-in")
        if state.get("encoder_model") != MFCC_ENCODER_ID or state.get("input_dim") != FEATURE_DIMENSION:
            raise ValueError("Checkpoint is not a 26-dimensional C3 MFCC projection")
        self.model = TripletProjection(FEATURE_DIMENSION, state["output_dim"], state.get("normalize", True))
        self.model.load_state_dict(state["model_state_dict"])
        self.model.to(self.device).eval()
        self.encoder_model = MFCC_ENCODER_ID
        self.encoder_revision = None
        self._bank = mel_filterbank(SAMPLE_RATE, N_FFT, N_MELS, F_MIN_HZ, F_MAX_HZ)
        self._basis = dct_basis(N_MFCC, N_MELS)

    @staticmethod
    def _audio(source: Any, sample_rate: int | None) -> np.ndarray:
        if isinstance(source, tuple) and len(source) == 2:
            source, sample_rate = source
        if isinstance(source, (str, Path)):
            return read_target_audio(Path(source), SAMPLE_RATE)
        audio = np.asarray(source, dtype=np.float64)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
            raise ValueError("Audio must be a nonempty finite mono or [time, channels] waveform")
        if sample_rate is None or int(sample_rate) <= 0:
            raise ValueError("A positive sample rate is required for array audio")
        sample_rate = int(sample_rate)
        if sample_rate != SAMPLE_RATE:
            divisor = math.gcd(sample_rate, SAMPLE_RATE)
            audio = resample_poly(audio, SAMPLE_RATE // divisor, sample_rate // divisor)
        return np.asarray(audio, dtype=np.float64)

    def embed_audio(self, source: Any, sample_rate: int | None = None) -> np.ndarray:
        audio = self._audio(source, sample_rate)
        feature = np.asarray(extract_mfcc_summary(audio, MFCC_SETTINGS,
                              self._bank, self._basis), dtype=np.float32)
        if feature.shape != (FEATURE_DIMENSION,) or not np.isfinite(feature).all():
            raise ValueError(f"C3 MFCC extractor returned invalid feature shape {feature.shape}")
        return feature

    def score(self, reference_audio: Any, candidate_audio: Any,
              sample_rate: int | None = None) -> SimilarityResult:
        return self.score_embeddings(self.embed_audio(reference_audio, sample_rate),
                                     self.embed_audio(candidate_audio, sample_rate))

    def score_embeddings(self, reference_embedding: Any,
                         candidate_embedding: Any) -> SimilarityResult:
        values = np.asarray([reference_embedding, candidate_embedding], dtype=np.float32)
        if values.shape != (2, FEATURE_DIMENSION) or not np.isfinite(values).all():
            raise ValueError("mfcc26 inputs must be finite vectors with shape [26]")
        with torch.inference_mode():
            projected = self.model(torch.as_tensor(values, dtype=torch.float32, device=self.device))
            distance = float(cosine_distance(projected[:1], projected[1:]).item())
        similarity = float(np.clip(1.0 - distance, -1.0, 1.0))
        return SimilarityResult("c4_mfcc26", similarity, distance)


class AdaptedScorer:
    """Load the frozen-CLAP projection checkpoint and score actual audio inputs."""
    def __init__(self, checkpoint: Path, *, clap_model: str | None = None,
                 clap_revision: str | None = None,
                 device: str | None = None, clap_local_files_only: bool = True,
                 allow_synthetic_checkpoint: bool = False,
                 allow_pilot_checkpoint: bool = False):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        state = torch.load(checkpoint, map_location=self.device, weights_only=True)
        if state.get("data_status") == SYNTHETIC_MARK and not allow_synthetic_checkpoint:
            raise ValueError("Refusing to use a synthetic-label checkpoint as a C3 perceptual scorer")
        if state.get("data_status") == PILOT_MARK and not allow_pilot_checkpoint:
            raise ValueError("Refusing to use a rehearsal pilot checkpoint without explicit opt-in")
        saved_model = state.get("encoder_model")
        saved_revision = state.get("encoder_revision")
        if saved_model == MFCC_ENCODER_ID:
            raise ValueError("This is an MFCC26 checkpoint; load it with MFCCAdaptedScorer")
        if saved_model in {None, "synthetic_or_unspecified_encoder"}:
            raise ValueError("This checkpoint has no real audio encoder metadata and cannot score audio")
        clap_model = clap_model or saved_model
        clap_revision = clap_revision or saved_revision
        if clap_model != saved_model or clap_revision != saved_revision:
            raise ValueError("Requested CLAP model/revision does not match the checkpoint metadata")
        if (clap_model != "laion/clap-htsat-unfused"
                or clap_revision != "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"
                or state.get("input_dim") != 512):
            raise ValueError("C4 CLAP checkpoints must use the pinned encoder revision and 512 input features")
        self.model = TripletProjection(state["input_dim"], state["output_dim"], state.get("normalize", True))
        self.model.load_state_dict(state["model_state_dict"])
        self.model.to(self.device).eval()
        self.clap_model = clap_model
        self.clap_revision = clap_revision
        self.encoder_model = clap_model
        self.encoder_revision = clap_revision
        self.clap_local_files_only = clap_local_files_only

    def score(self, reference_audio: Any, candidate_audio: Any,
              sample_rate: int | None = None) -> SimilarityResult:
        ref = prepare_audio(reference_audio, sample_rate)
        candidate = prepare_audio(candidate_audio, sample_rate)
        base = _clap_embeddings(ref, candidate, self.clap_model, self.clap_revision,
                                self.clap_local_files_only)
        return self.score_embeddings(base[0], base[1])

    def score_embeddings(self, reference_embedding: Any,
                         candidate_embedding: Any) -> SimilarityResult:
        base = np.asarray([reference_embedding, candidate_embedding], dtype=np.float32)
        if (base.shape != (2, 512) or base.dtype != np.float32
                or not np.isfinite(base).all()
                or base.shape[1] != self.model.projection.in_features):
            raise ValueError("Pinned CLAP embeddings must be finite float32 vectors with shape [2, 512]")
        with torch.inference_mode():
            projected = self.model(torch.as_tensor(base, dtype=torch.float32, device=self.device))
            distance = float(cosine_distance(projected[:1], projected[1:]).item())
        similarity = float(np.clip(1.0 - distance, -1.0, 1.0))
        return SimilarityResult("c4", similarity, distance)


def score_reference_against_candidates(reference_audio: Any, candidate_audios: list[Any],
                                       method: str = "c4", **kwargs):
    """Return candidates ranked most-to-least similar using the selected ruler.

    ``c4`` requires a trained projection checkpoint and frozen CLAP embeddings;
    frozen baselines can be called by name (``mfcc``, ``stft``, ``clap``).
    The checkpoint-taking C4 route is intentionally explicit in this initial API.
    """
    scorer = kwargs.pop("scorer", None)
    if method == "c4":
        if not isinstance(scorer, (AdaptedScorer, MFCCAdaptedScorer)):
            raise ValueError("Pass a trained C4 AdaptedScorer or MFCCAdaptedScorer for method='c4'")
        return sorted([(candidate, scorer.score(reference_audio, candidate,
                                                kwargs.get("sample_rate")))
                       for candidate in candidate_audios],
                      key=lambda item: item[1].similarity, reverse=True)
    return rank_candidates(reference_audio, candidate_audios, method=method, **kwargs)


__all__ = ["AdaptedScorer", "MFCCAdaptedScorer", "score_reference_against_candidates", "score_similarity"]
