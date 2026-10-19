"""Run all available frozen baselines on one identical corpus audio pair."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from c4_metric.c3_adapter import AdaptedScorer
from c4_metric.similarity import SimilarityResult, _cosine, baseline_availability, score_similarity


def read_dicts(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def run(reference_id: str, candidate_id: str, manifest_path: Path,
        output_path: Path, clap_revision: str | None = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a",
        embedding_cache: Path | None = None, checkpoint: Path | None = None,
        allow_synthetic_checkpoint: bool = False) -> dict:
    rows = read_dicts(manifest_path)
    by_id = {row["sample_id"]: row for row in rows}
    if reference_id not in by_id or candidate_id not in by_id:
        raise ValueError("Reference/candidate ID missing from supplied manifest")
    result = {
        "data_status": "baseline_software_smoke_test_not_human_evidence",
        "reference_id": reference_id, "candidate_id": candidate_id,
        "score_direction": "higher similarity is better for every implemented method",
        "methods": {},
        "availability": baseline_availability(),
    }
    cached_embeddings = {}
    cache_meta = {}
    if embedding_cache and embedding_cache.is_file():
        meta_path = embedding_cache.with_suffix(".json")
        if meta_path.is_file():
            cache_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if cache_meta.get("model") == "laion/clap-htsat-unfused" and cache_meta.get("revision") == clap_revision:
            with np.load(embedding_cache, allow_pickle=False) as archive:
                cached_embeddings = {sid: vector for sid, vector in zip(
                    archive["sample_ids"].astype(str), archive["embeddings"])}
    for method in ("mfcc", "stft", "clap", "synth_aware", "cdpam"):
        try:
            if method == "synth_aware":
                score = score_similarity(None, None, method, reference_id=reference_id,
                                          candidate_id=candidate_id, manifest_path=manifest_path)
            else:
                left = ROOT / by_id[reference_id]["raw_audio_path"]
                right = ROOT / by_id[candidate_id]["raw_audio_path"]
                try:
                    score = score_similarity(left, right, method, clap_revision=clap_revision,
                                             clap_local_files_only=(method == "clap"))
                    source = "local model checkpoint" if method == "clap" else "audio input"
                except (RuntimeError, OSError, ImportError) as error:
                    if method != "clap" or reference_id not in cached_embeddings or candidate_id not in cached_embeddings:
                        raise error
                    sim = float(np.clip(_cosine(cached_embeddings[reference_id],
                                                cached_embeddings[candidate_id]), -1.0, 1.0))
                    score = SimilarityResult("clap", sim, 1.0 - sim)
                    source = "pinned pretrained CLAP embedding cache; model checkpoint not locally loadable"
            if method == "synth_aware":
                source = "normalized synthesizer parameters"
            result["methods"][method] = {"status": "tested", "similarity": score.similarity,
                                         "distance": score.distance, "source": source}
        except (RuntimeError, OSError, ImportError) as error:
            result["methods"][method] = {"status": "unavailable", "reason": str(error)}
    if checkpoint:
        try:
            scorer = AdaptedScorer(checkpoint, allow_synthetic_checkpoint=allow_synthetic_checkpoint)
            left = ROOT / by_id[reference_id]["raw_audio_path"]
            right = ROOT / by_id[candidate_id]["raw_audio_path"]
            score = scorer.score(left, right)
            result["methods"]["c4"] = {"status": "tested", "similarity": score.similarity,
                                        "distance": score.distance, "source": "frozen CLAP plus trained projection"}
        except (RuntimeError, OSError, ImportError, ValueError) as error:
            result["methods"]["c4"] = {"status": "unavailable", "reason": str(error)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/raw/corpus_v4/manifest.csv")
    parser.add_argument("--triplets", type=Path, default=ROOT / "c4_metric/synthetic_data/clap_triplets.csv")
    parser.add_argument("--reference-id")
    parser.add_argument("--candidate-id")
    parser.add_argument("--output", type=Path, default=ROOT / "c4_metric/outputs/baseline_smoke.json")
    parser.add_argument("--embedding-cache", type=Path,
                        default=ROOT / "c4_metric/synthetic_data/clap_embedding_cache.npz")
    parser.add_argument("--checkpoint", type=Path,
                        help="Optional trained projection checkpoint to test adapted C4 on this same pair")
    parser.add_argument("--allow-synthetic-checkpoint", action="store_true",
                        help="Permit a synthetic-label checkpoint for software smoke checks only")
    parser.add_argument("--clap-revision", default="8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a")
    args = parser.parse_args()
    reference_id, candidate_id = args.reference_id, args.candidate_id
    if not reference_id or not candidate_id:
        first = read_dicts(args.triplets)[0]
        reference_id = reference_id or first.get("reference_sample_id")
        candidate_id = candidate_id or first.get("candidate_a_sample_id")
    print(json.dumps(run(reference_id, candidate_id, args.manifest, args.output,
                         args.clap_revision, args.embedding_cache, args.checkpoint,
                         args.allow_synthetic_checkpoint), indent=2))


if __name__ == "__main__":
    main()
