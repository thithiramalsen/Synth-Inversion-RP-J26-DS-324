"""Score similarity between two audio files with C4 or a frozen baseline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from c4_metric.c3_adapter import AdaptedScorer
from c4_metric.similarity import score_similarity


def similarity_index_0_to_100(similarity: float, method: str) -> float:
    """Rescale a method's documented similarity range for display only."""
    if method in {"mfcc", "stft", "ms_stft", "synth_aware"}:
        return min(100.0, max(0.0, similarity * 100.0))
    return min(100.0, max(0.0, (similarity + 1.0) * 50.0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="Reference audio file")
    parser.add_argument("candidate", type=Path, help="Candidate audio file")
    parser.add_argument("--method", choices=("c4", "clap", "mfcc", "stft", "ms_stft"), default="c4",
                        help="Scoring method (default: c4)")
    parser.add_argument("--checkpoint", type=Path,
                        default=ROOT / "c4_metric/outputs/synthetic_training/best_model.pt",
                        help="C4 projection checkpoint (used only with --method c4)")
    parser.add_argument("--allow-synthetic-checkpoint", action="store_true",
                        help="Allow C4's synthetic-label checkpoint for software demonstration only")
    parser.add_argument("--output", type=Path, help="Optional path to save the JSON result")
    args = parser.parse_args()

    for label, path in (("Reference", args.reference), ("Candidate", args.candidate)):
        if not path.is_file():
            parser.error(f"{label} audio file does not exist: {path}")

    if args.method == "c4":
        scorer = AdaptedScorer(
            args.checkpoint,
            clap_local_files_only=True,
            allow_synthetic_checkpoint=args.allow_synthetic_checkpoint,
        )
        score = scorer.score(args.reference, args.candidate)
        note = (
            "This checkpoint was trained on synthetic preferences. This score is a software "
            "demonstration, not a validated human-perceptual similarity estimate. "
            if args.allow_synthetic_checkpoint else
            "Score from the supplied C4 checkpoint; human alignment depends on its training and evaluation data."
        )
        note += " The 0-100 display is a rescaled score, not a literal perceptual percentage."
    else:
        score = score_similarity(
            args.reference,
            args.candidate,
            args.method,
            clap_local_files_only=True,
        )
        note = "The 0-100 display is a rescaled score, not a literal percentage of perceptual similarity."

    # MFCC/STFT are already mapped to [0, 1]; CLAP/C4 cosine is in [-1, 1].
    # Put both conventions onto a readable 0-100 display scale without calling
    # the result a calibrated percentage of human-perceived similarity.
    similarity_index = similarity_index_0_to_100(score.similarity, args.method)
    result = {
        "reference": str(args.reference.resolve()),
        "candidate": str(args.candidate.resolve()),
        "method": score.method,
        "similarity": score.similarity,
        "similarity_index_0_to_100": round(similarity_index, 2),
        "similarity_display": f"{similarity_index:.1f}/100 (rescaled index, not a true percentage)",
        "distance": score.distance,
        "score_direction": "higher similarity means more similar; lower distance means more similar",
        "note": note,
    }
    serialized = json.dumps(result, indent=2)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
