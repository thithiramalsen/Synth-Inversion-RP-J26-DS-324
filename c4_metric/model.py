"""Small trainable projection head and the required C4 triplet-margin loss."""
from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class TripletProjection(nn.Module):
    """Project frozen encoder vectors; output uses cosine distance (lower wins)."""
    def __init__(self, input_dim: int, output_dim: int = 128, normalize: bool = True):
        super().__init__()
        if input_dim < 1 or output_dim < 1:
            raise ValueError("Embedding dimensions must be positive")
        self.projection = nn.Linear(input_dim, output_dim, bias=False)
        self.normalize = normalize

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        if embeddings.ndim != 2:
            raise ValueError("Expected [batch, embedding_dim] tensor")
        if embeddings.shape[1] != self.projection.in_features:
            raise ValueError("Input embedding dimension does not match projection head")
        result = self.projection(embeddings)
        return F.normalize(result, p=2, dim=1) if self.normalize else result


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    if a.shape != b.shape or a.ndim != 2:
        raise ValueError("Cosine distance inputs must have matching [batch, dim] shapes")
    return 1.0 - F.cosine_similarity(a, b, dim=1, eps=1e-8)


def triplet_margin_loss(anchor: torch.Tensor, positive: torch.Tensor,
                        negative: torch.Tensor, margin: float = 0.2,
                        reduction: str = "mean") -> torch.Tensor:
    """L = max(0, d(A,P) - d(A,N) + margin), with cosine distance."""
    if margin < 0:
        raise ValueError("margin must be nonnegative")
    if anchor.shape != positive.shape or anchor.shape != negative.shape:
        raise ValueError("Anchor, positive, and negative tensors must have matching shapes")
    if anchor.ndim != 2 or anchor.shape[0] == 0:
        raise ValueError("Triplet tensors must be nonempty [batch, dim] tensors")
    if not (torch.isfinite(anchor).all() and torch.isfinite(positive).all() and torch.isfinite(negative).all()):
        raise ValueError("Triplet tensors must contain only finite values")
    raw = cosine_distance(anchor, positive) - cosine_distance(anchor, negative) + margin
    losses = torch.clamp(raw, min=0.0)
    if reduction == "mean":
        return losses.mean()
    if reduction == "sum":
        return losses.sum()
    if reduction == "none":
        return losses
    raise ValueError("reduction must be 'mean', 'sum', or 'none'")
