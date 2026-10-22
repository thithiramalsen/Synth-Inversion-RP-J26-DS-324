"""Build the frozen, private C3 study bundle: 8 scored cases, 1 practice, audio and provenance.

Targets come from a seeded sample of VALIDATION sounds (never test). For each target the plain
top-k and the C3 (MMR) set are built from the same audio shortlist with the tested c3 code.
A target is skipped only if the two sets are identical or the audio fails a technical check;
every skip is logged. No human response or quality judgement is used.

Never serve the bundle folder: bundle.json holds sample IDs, which set is which, and the
headphone answer keys.

Usage (repository root):
    python -m c3_recommendation.human_study.build [--output data/processed/c3_v4/human_study_bundle_v3]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "c3_recommendation" / "src"))

from c3.config import load_config  # noqa: E402
from c3.data_sources import make_source  # noqa: E402
from c3.metrics import PoolArrays, metrics_from_indices  # noqa: E402
from c3.param_space import ParamDistance  # noqa: E402
from c3.relevance import FeatureCosineRelevance  # noqa: E402
from c3.retrieval import pool_from_scores  # noqa: E402
from c3.selection import mmr_indices  # noqa: E402
from c3.splits import BANK, VAL, Splits, load_manifest  # noqa: E402

from .design import (  # noqa: E402
    CANDIDATE_POOL, LABELS, N_SCORED, NAMES, OPERATING_POINT, SEED, TARGET, VERSION, assignment,
    display_order, eligible,
)

DEFAULT_BUNDLE = ROOT / "data/processed/c3_v4/human_study_bundle_v2"
SCREEN_DIR = ROOT / "survey/deploy/study"
SILENCE_DBFS = -60.0


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def audio_problem(samples: np.ndarray) -> str:
    """Technical QA only: finite, not clipped, not silent."""
    if not np.isfinite(samples).all():
        return "non-finite samples"
    peak = float(np.max(np.abs(samples)))
    if peak >= 1.0:
        return "clipped"
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms == 0.0 or 20 * np.log10(rms) < SILENCE_DBFS:
        return "silent"
    return ""


def save_playback(path: Path, samples: np.ndarray) -> dict:
    """16-bit PCM copy of the processed corpus audio; no loudness normalisation."""
    sf.write(path, samples, 44100, subtype="PCM_16")
    return {"file": path.name, "sha256": sha(path)}


def build(output: Path) -> None:
    output = Path(output)
    if output.exists():
        raise ValueError("Use a new output directory; existing study bundles are never overwritten")
    cfg = load_config()
    if cfg["data.source"] != "corpus_v4":
        raise ValueError("The study plays audio: data.source must be corpus_v4")
    source = make_source(cfg)
    if list(source.schema.names) != list(NAMES):
        raise ValueError("Unexpected parameter order")
    unit = source.params_unit()
    split_dir = cfg.path("outputs_dir") / "splits"
    splits = Splits.from_config(cfg, load_manifest(split_dir))
    bank_ids = np.asarray(splits.ids(BANK), dtype=object)
    screened = splits.get_targets(VAL, CANDIDATE_POOL, SEED)
    if set(screened) & set(bank_ids):
        raise ValueError("A study target is in the candidate bank")

    p = OPERATING_POINT
    features_dir = cfg.path("outputs_dir") / "features"
    relevance = FeatureCosineRelevance.from_cache(features_dir, p["representation"])
    relevance.fit(list(bank_ids))
    distance = ParamDistance.from_schema(source.schema, method=cfg["param_distance.method"])
    bank_position = {cid: i for i, cid in enumerate(bank_ids)}
    bank_vectors = unit.loc[bank_ids].to_numpy(np.float64)

    (output / "audio").mkdir(parents=True)
    cases, provenance, skipped = [], [], []
    for screen_rank, target in enumerate(screened):
        if len(cases) == N_SCORED + 1:
            break
        pool = pool_from_scores(relevance.score_bank(target), bank_ids, p["pool_size"])
        vectors = bank_vectors[[bank_position[c] for c in pool["candidate_id"]]]
        arrays = PoolArrays(pool["candidate_id"].to_numpy(), pool["relevance"].to_numpy(np.float64),
                            pool["audio_rank"].to_numpy(), distance.cdist(vectors, vectors))
        top = list(range(p["k"]))
        chosen = {"topk": top,
                  "mmr": mmr_indices(arrays.relevance, arrays.similarity, p["k"], p["lam"], p["relevance_scaling"])}
        ids = {m: [str(arrays.candidate_ids[i]) for i in idx] for m, idx in chosen.items()}
        ok, reason = eligible(ids["topk"], ids["mmr"])
        unique = list(dict.fromkeys(ids["topk"] + ids["mmr"]))
        audio = {}
        if ok:
            for sample_id in [target, *unique]:
                samples, _ = source.audio(sample_id)
                problem = audio_problem(samples)
                if problem:
                    ok, reason = False, f"technical: {problem} ({sample_id})"
                    break
                audio[sample_id] = samples
        if not ok:
            skipped.append({"screen_rank": screen_rank, "sample_id": target, "reason": reason})
            continue

        case_id = f"case_{len(cases) + 1:02d}" if len(cases) < N_SCORED else "practice"
        numbered = [unique[i] for i in display_order(case_id, len(unique))]
        number_of = {sample_id: n for n, sample_id in enumerate(numbered, start=1)}
        position_of = {str(c): i for i, c in enumerate(arrays.candidate_ids)}
        sounds = []
        for sample_id in numbered:
            n = number_of[sample_id]
            playback = save_playback(output / "audio" / f"{case_id}_s{n}.wav", audio[sample_id])
            sounds.append({"sound_id": f"{case_id}_s{n}", "number": n, "audio": playback,
                           "params": [round(float(v), 4) for v in unit.loc[sample_id]]})
        target_audio = save_playback(output / "audio" / f"{case_id}_target.wav", audio[target])
        sets = {m: sorted(number_of[s] for s in ids[m]) for m in ids}
        metrics = {m: {k: float(v) for k, v in metrics_from_indices(chosen[m], arrays, (), top).items()
                       if k in ("mean_rel", "min_rel", "mean_pair_dist", "min_pair_dist", "overlap_with_topk")}
                   for m in chosen}
        cases.append({"case_id": case_id, "target_audio": target_audio, "sounds": sounds, "sets": sets})
        provenance.append({
            "case_id": case_id, "target_sample_id": target, "screen_rank": screen_rank, "split": VAL,
            "sounds": [{"number": number_of[s], "sample_id": s, "relevance": float(arrays.relevance[position_of[s]]),
                        "audio_rank": int(arrays.audio_rank[position_of[s]]),
                        "in_topk": s in ids["topk"], "in_mmr": s in ids["mmr"]} for s in numbered],
            "set_metrics": metrics,
        })
        print(f"Built {case_id}: target {target} (screen rank {screen_rank}), "
              f"{len(unique)} distinct sounds, {len(set(ids['topk']) & set(ids['mmr']))} shared", flush=True)
    if len(cases) != N_SCORED + 1:
        raise ValueError(f"Only {len(cases)} eligible cases in the first {CANDIDATE_POOL} screened targets")

    # Reuse the existing six-trial headphone check and volume reference, verified by hash.
    screen = json.loads((SCREEN_DIR / "bundle.json").read_text(encoding="utf-8"))
    for item in [*screen["headphones"], screen["calibration"]]:
        path = SCREEN_DIR / "audio" / item["path"]
        if sha(path) != item["sha256"]:
            raise ValueError("Headphone setup asset changed: " + item["path"])
        shutil.copyfile(path, output / "audio" / path.name)

    payload = {
        "version": VERSION, "seed": SEED, "test_evaluated": False, "operating_point": OPERATING_POINT,
        "parameter_names": list(NAMES), "parameter_labels": list(LABELS),
        "cases": cases, "headphones": screen["headphones"], "volume": screen["calibration"],
        "selection": (f"Seeded sample of {CANDIDATE_POOL} validation targets (seed {SEED}) screened in order; "
                      "skip only identical sets or technical audio failure; first 8 eligible scored, 9th practice"),
        "skipped": skipped, "provenance": provenance,
        "assignments": [assignment(i) for i in range(TARGET)],
        "sources": {"config": sha(cfg.source_path), "split_summary": sha(split_dir / "split_summary.json"),
                    "features_meta": sha(features_dir / "features_meta.json"),
                    "builder": sha(Path(__file__)), "design": sha(Path(__file__).with_name("design.py"))},
    }
    write_json(output / "bundle.json", payload)
    write_json(output / "manifest.json", {
        "status": "complete_rehearsal_bundle", "version": VERSION, "test_evaluated": False,
        "files": {f.relative_to(output).as_posix(): sha(f) for f in sorted(output.rglob("*"))
                  if f.is_file() and f.name != "manifest.json"}})
    print(f"Bundle saved: {output}. {len(skipped)} screened targets skipped. Validation targets only.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_BUNDLE)
    build(parser.parse_args().output)
