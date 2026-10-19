"""Small stable API for C3 or other callers to rank audio candidates."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from c4_metric.model import TripletProjection, cosine_distance
from c4_metric.similarity import (SimilarityResult, _clap_embeddings, prepare_audio,
                                  rank_candidates, score_similarity)

SYNTHETIC_MARK = "SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"


class AdaptedScorer:
    """Load the frozen-CLAP projection checkpoint and score actual audio inputs."""
    def __init__(self, checkpoint: Path, *, clap_model: str | None = None,
                 clap_revision: str | None = None,
                 device: str | None = None, clap_local_files_only: bool = True,
                 allow_synthetic_checkpoint: bool = False):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        state = torch.load(checkpoint, map_location=self.device, weights_only=True)
        if state.get("data_status") == SYNTHETIC_MARK and not allow_synthetic_checkpoint:
            raise ValueError("Refusing to use a synthetic-label checkpoint as a C3 perceptual scorer")
        saved_model = state.get("encoder_model")
        saved_revision = state.get("encoder_revision")
        if saved_model in {None, "synthetic_or_unspecified_encoder"}:
            raise ValueError("This checkpoint has no real audio encoder metadata and cannot score audio")
        clap_model = clap_model or saved_model
        clap_revision = clap_revision or saved_revision
        if clap_model != saved_model or clap_revision != saved_revision:
            raise ValueError("Requested CLAP model/revision does not match the checkpoint metadata")
        self.model = TripletProjection(state["input_dim"], state["output_dim"], state.get("normalize", True))
        self.model.load_state_dict(state["model_state_dict"])
        self.model.to(self.device).eval()
        self.clap_model = clap_model
        self.clap_revision = clap_revision
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
        if base.ndim != 2 or base.shape[1] != self.model.projection.in_features:
            raise ValueError("Frozen embeddings do not match the checkpoint input dimension")
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
        if not isinstance(scorer, AdaptedScorer):
            raise ValueError("Pass scorer=AdaptedScorer(checkpoint) for method='c4'")
        return sorted([(candidate, scorer.score(reference_audio, candidate,
                                                kwargs.get("sample_rate")))
                       for candidate in candidate_audios],
                      key=lambda item: item[1].similarity, reverse=True)
    return rank_candidates(reference_audio, candidate_audios, method=method, **kwargs)


__all__ = ["AdaptedScorer", "score_reference_against_candidates", "score_similarity"]
