"""Leakage-checked human triplet benchmark for adapted C4 and frozen baselines."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import sys
import platform
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from c4_metric.c3_adapter import AdaptedScorer, MFCCAdaptedScorer
from c4_metric.similarity import SimilarityResult, _cosine, baseline_availability, score_similarity

MARK = "SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"
DEFAULT_METHODS = ("mfcc", "ms_stft", "clap", "cdpam", "synth_aware")
KNOWN_METHODS = set(DEFAULT_METHODS) | {"stft", "c4"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _split_rows_sha256(rows: list[dict], split_name: str) -> str:
    selected = [{key: value for key, value in row.items() if key != "audio_component_id"}
                for row in rows if row.get("split") == split_name]
    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _triplet_key(row: dict) -> tuple[str, str, str]:
    """Stable key when the survey randomized left/right candidate order."""
    return (str(row["anchor_id"]), *sorted((str(row["positive_id"]), str(row["negative_id"]))))


def _audio_components(rows: list[dict]) -> dict[str, str]:
    """Find connected audio identity groups so all inferential units are explicit."""
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for index, row in enumerate(rows, start=2):
        ids = [str(row.get(key, "")).strip() for key in ("anchor_id", "positive_id", "negative_id")]
        if any(not value for value in ids) or len(set(ids)) != 3:
            raise ValueError(f"Invalid anchor/positive/negative audio identities on split row {index}")
        for value in ids:
            find(value)
        union(ids[0], ids[1])
        union(ids[0], ids[2])

    members: dict[str, list[str]] = defaultdict(list)
    for sample_id in list(parent):
        members[find(sample_id)].append(sample_id)
    group_by_id: dict[str, str] = {}
    for sample_ids in members.values():
        stable_id = hashlib.sha256("\n".join(sorted(sample_ids)).encode("utf-8")).hexdigest()[:16]
        for sample_id in sample_ids:
            group_by_id[sample_id] = f"audio_group_{stable_id}"
    return group_by_id


def _attach_audio_groups(rows: list[dict]) -> tuple[list[dict], dict]:
    if not rows or "split" not in rows[0]:
        raise ValueError("Input needs train/validation/test split assignments; create grouped splits first")
    unknown = sorted(set(row.get("split", "") for row in rows) - {"train", "validation", "test"})
    if unknown:
        raise ValueError(f"Unexpected split labels: {unknown}")
    group_by_id = _audio_components(rows)
    split_audio: dict[str, set[str]] = defaultdict(set)
    split_groups: dict[str, set[str]] = defaultdict(set)
    all_rows = []
    for row in rows:
        copied = dict(row)
        ids = (row["anchor_id"], row["positive_id"], row["negative_id"])
        groups = {group_by_id[sample_id] for sample_id in ids}
        if len(groups) != 1:
            raise AssertionError("Triplet audio IDs must be in one connected component")
        copied["audio_component_id"] = groups.pop()
        all_rows.append(copied)
        split_audio[row["split"]].update(ids)
        split_groups[row["split"]].add(copied["audio_component_id"])
    split_names = ("train", "validation", "test")
    if any(not any(row["split"] == name for row in all_rows) for name in split_names):
        raise ValueError("Nonempty train, validation, and test splits are required")
    for index, left in enumerate(split_names):
        for right in split_names[index + 1:]:
            overlap = split_audio[left] & split_audio[right]
            if overlap:
                raise ValueError(f"Audio identity leakage between {left} and {right}: {len(overlap)} IDs")
            if split_groups[left] & split_groups[right]:
                raise ValueError(f"Audio component leakage between {left} and {right}")
    participant_folds: dict[str, set[str]] = defaultdict(set)
    for row in all_rows:
        if row.get("participant_id"):
            participant_folds[row["participant_id"]].add(row["split"])
    integrity = {
        "audio_identity_overlap_across_splits": 0,
        "audio_component_overlap_across_splits": 0,
        "audio_components_by_split": {name: len(split_groups[name]) for name in split_names},
        "unique_audio_ids_by_split": {name: len(split_audio[name]) for name in split_names},
        "participants_in_multiple_splits": sum(len(folds) > 1 for folds in participant_folds.values()),
        "participant_split_scope": "Audio comparisons are held out; listeners may contribute responses to multiple folds.",
    }
    return all_rows, integrity


def _choice_accuracy(row: dict, method: str) -> float:
    positive = float(row[f"sim_{method}_positive"])
    negative = float(row[f"sim_{method}_negative"])
    difference = positive - negative
    if abs(difference) <= 1e-12:
        return 0.5
    return 1.0 if difference > 0 else 0.0


def _accuracy_values(rows: list[dict], method: str) -> np.ndarray:
    return np.asarray([_choice_accuracy(row, method) for row in rows], dtype=np.float64)


def _participant_accuracy(rows: list[dict], values: np.ndarray) -> dict[str, float]:
    groups: dict[str, list[float]] = defaultdict(list)
    for index, row in enumerate(rows):
        participant = str(row.get("participant_id") or f"unidentified_row_{index}")
        groups[participant].append(float(values[index]))
    return {participant: float(np.mean(items)) for participant, items in groups.items()}


def _metric_summary(rows: list[dict], method: str, bootstrap_draws: int,
                    seed: int, *, aggregate_mode: bool = False) -> tuple[dict, dict[str, float]]:
    values = _accuracy_values(rows, method)
    if aggregate_mode:
        summary = {
            "triplet_choice_accuracy": float(np.mean(values)),
            "participant_macro_accuracy": None,
            "audio_component_bootstrap_95_percent_ci": _audio_component_bootstrap_ci(
                rows, values, bootstrap_draws, seed),
            "aggregate_comparisons": len(rows),
            "unique_participants": None,
            "unique_triplets": len({_triplet_key(row) for row in rows}),
            "unique_audio_components": len({row["audio_component_id"] for row in rows}),
            "model_score_ties_counted_as_half_correct": int(np.sum(values == 0.5)),
        }
        return summary, {}
    participants = _participant_accuracy(rows, values)
    interval = _two_way_bootstrap_ci(rows, values, bootstrap_draws, seed)
    summary = {
        "triplet_choice_accuracy": float(np.mean(values)),
        "participant_macro_accuracy": float(np.mean(list(participants.values()))),
        "two_way_cluster_bootstrap_95_percent_ci": interval,
        "responses": len(rows),
        "unique_participants": len(participants),
        "unique_triplets": len({_triplet_key(row) for row in rows}),
        "unique_audio_components": len({row["audio_component_id"] for row in rows}),
        "model_score_ties_counted_as_half_correct": int(np.sum(values == 0.5)),
    }
    return summary, participants


def _audio_component_bootstrap_ci(rows: list[dict], values: np.ndarray, draws: int,
                                  seed: int) -> list[float]:
    components = sorted({str(row["audio_component_id"]) for row in rows})
    lookup = {component: index for index, component in enumerate(components)}
    indexes = np.asarray([lookup[str(row["audio_component_id"])] for row in rows], dtype=np.int64)
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=np.float64)
    for draw in range(draws):
        counts = np.bincount(rng.integers(0, len(components), size=len(components)),
                             minlength=len(components))
        weights = counts[indexes]
        estimates[draw] = float(np.dot(weights, values) / weights.sum()) if weights.sum() else float(values.mean())
    return [float(np.quantile(estimates, .025)), float(np.quantile(estimates, .975))]


def _paired_comparison_test(rows: list[dict], left_values: np.ndarray,
                            right_values: np.ndarray) -> dict:
    deltas_by_key: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row, left, right in zip(rows, left_values, right_values, strict=True):
        deltas_by_key[_triplet_key(row)].append(float(left - right))
    deltas = [float(np.mean(values)) for values in deltas_by_key.values()]
    nonzero = [value for value in deltas if abs(value) > 1e-12]
    wins = sum(value > 0 for value in nonzero)
    return {
        "mean_accuracy_difference_c4_minus_baseline": float(np.mean(deltas)) if deltas else None,
        "aggregate_comparisons_paired": len(deltas),
        "comparisons_with_non_tied_delta": len(nonzero),
        "c4_higher_accuracy_comparisons": int(wins),
        "paired_sign_test_p_value": float(binomtest(wins, len(nonzero), .5,
                                              alternative="two-sided").pvalue) if nonzero else 1.0,
    }


def _two_way_bootstrap_ci(rows: list[dict], values: np.ndarray, draws: int,
                          seed: int) -> list[float]:
    """Pigeonhole bootstrap across independent listeners and disjoint audio groups."""
    people = sorted({str(row.get("participant_id") or f"unidentified_row_{i}")
                     for i, row in enumerate(rows)})
    components = sorted({str(row["audio_component_id"]) for row in rows})
    p_lookup = {value: i for i, value in enumerate(people)}
    c_lookup = {value: i for i, value in enumerate(components)}
    p_idx = np.asarray([p_lookup[str(row.get("participant_id") or f"unidentified_row_{i}")]
                        for i, row in enumerate(rows)], dtype=np.int64)
    c_idx = np.asarray([c_lookup[str(row["audio_component_id"])] for row in rows], dtype=np.int64)
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=np.float64)
    for draw in range(draws):
        p_counts = np.bincount(rng.integers(0, len(people), size=len(people)), minlength=len(people))
        c_counts = np.bincount(rng.integers(0, len(components), size=len(components)), minlength=len(components))
        weights = p_counts[p_idx] * c_counts[c_idx]
        total = int(weights.sum())
        estimates[draw] = float(np.dot(weights, values) / total) if total else float(np.mean(values))
    return [float(np.quantile(estimates, .025)), float(np.quantile(estimates, .975))]


def _paired_sign_test(left: dict[str, float], right: dict[str, float]) -> dict:
    shared = sorted(set(left) & set(right))
    deltas = [left[participant] - right[participant] for participant in shared]
    nonzero = [value for value in deltas if abs(value) > 1e-12]
    wins = sum(value > 0 for value in nonzero)
    p_value = float(binomtest(wins, len(nonzero), .5, alternative="two-sided").pvalue) if nonzero else 1.0
    return {
        "participant_macro_accuracy_difference_c4_minus_baseline": float(np.mean(deltas)) if deltas else None,
        "participants_compared": len(shared),
        "participants_with_non_tied_delta": len(nonzero),
        "c4_higher_accuracy_participants": int(wins),
        "participant_level_paired_sign_test_p_value": p_value,
    }


def _holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda pair: pair[1])
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - rank) * value))
        adjusted[name] = running
    return adjusted


def _triplet_hard_cases(rows: list[dict], methods: list[str], *, minimum_raters: int = 5,
                        minimum_triplets: int = 5) -> dict:
    by_triplet: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_triplet[_triplet_key(row)].append(row)
    cases = {"high_human_consensus": [], "ambiguous_human_preference": []}
    for triplet_rows in by_triplet.values():
        votes = [str(row["positive_id"]) for row in triplet_rows]
        if len(votes) < minimum_raters:
            continue
        consensus = max(Counter(votes).values()) / len(votes)
        if consensus >= 0.80:
            cases["high_human_consensus"].extend(triplet_rows)
        elif consensus <= 0.67:
            cases["ambiguous_human_preference"].extend(triplet_rows)
    results = {}
    for name, case_rows in cases.items():
        triplet_count = len({_triplet_key(row) for row in case_rows})
        if triplet_count < minimum_triplets:
            results[name] = {
                "status": "insufficient_data",
                "unique_triplets_with_at_least_5_raters": triplet_count,
                "minimum_triplets_for_summary": minimum_triplets,
            }
            continue
        results[name] = {
            "status": "exploratory_test_subset",
            "unique_triplets_with_at_least_5_raters": triplet_count,
            "responses": len(case_rows),
            "minimum_raters_per_triplet": minimum_raters,
            "accuracy_by_method": {method: float(np.mean(_accuracy_values(case_rows, method)))
                                   for method in methods},
        }
    explicit: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for key in ("case_type", "comparison_type", "hard_case_type"):
            label = str(row.get(key, "")).strip()
            if label:
                explicit[key][label].append(row)
    for key, categories in explicit.items():
        results[f"predefined_{key}"] = {}
        for label, case_rows in sorted(categories.items()):
            triplet_count = len({_triplet_key(row) for row in case_rows})
            if triplet_count < minimum_triplets:
                results[f"predefined_{key}"][label] = {
                    "status": "insufficient_data",
                    "unique_triplets": triplet_count,
                    "minimum_triplets_for_summary": minimum_triplets,
                }
            else:
                results[f"predefined_{key}"][label] = {
                    "status": "provided_case_label",
                    "unique_triplets": triplet_count,
                    "responses": len(case_rows),
                    "accuracy_by_method": {method: float(np.mean(_accuracy_values(case_rows, method)))
                                           for method in methods},
                }
    return results


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def evaluate(split_path: Path, manifest_path: Path, output_dir: Path, *,
             checkpoint: Path | None = None,
             methods: tuple[str, ...] = DEFAULT_METHODS,
             bootstrap_draws: int = 2000, seed: int = 20261014,
             allow_synthetic: bool = False,
             embedding_path: Path | None = None) -> dict:
    if bootstrap_draws < 100:
        raise ValueError("Use at least 100 bootstrap draws")
    source_rows = read_csv(split_path)
    rows, split_integrity = _attach_audio_groups(source_rows)
    statuses = {str(row.get("data_status", "")).strip() for row in rows
                if str(row.get("data_status", "")).strip()}
    if not statuses:
        raise ValueError("Every preference row must include data_status so synthetic and human data stay distinct")
    synthetic = any("SYNTHETIC" in status for status in statuses)
    if synthetic and any("SYNTHETIC" not in status for status in statuses):
        raise ValueError("Do not mix synthetic and human preference triplets")
    if not synthetic and statuses != {"human_response"}:
        raise ValueError(f"Unrecognized human-data status values: {sorted(statuses)}")
    if synthetic and not allow_synthetic:
        raise ValueError("Synthetic labels require explicit --allow-synthetic")
    if not synthetic and not checkpoint:
        raise ValueError("Human-response benchmark requires the adapted C4 --checkpoint")
    if not manifest_path.is_file():
        raise ValueError(f"Audio manifest does not exist: {manifest_path}")
    manifest_rows = read_csv(manifest_path)
    if not manifest_rows or "sample_id" not in manifest_rows[0]:
        raise ValueError("Manifest must contain sample_id and audio paths")
    audio_by_id = {row["sample_id"].strip(): row for row in manifest_rows}
    if len(audio_by_id) != len(manifest_rows):
        raise ValueError("Manifest contains duplicate sample IDs")
    all_ids = {sid for row in rows for sid in
               (row["anchor_id"], row["positive_id"], row["negative_id"])}
    missing_ids = all_ids - audio_by_id.keys()
    if missing_ids:
        raise ValueError(f"Manifest is missing {len(missing_ids)} split audio IDs: {sorted(missing_ids)[:8]}")

    requested = list(dict.fromkeys(methods))
    if checkpoint and "c4" not in requested:
        requested.append("c4")
    unknown = set(requested) - KNOWN_METHODS
    if unknown:
        raise ValueError(f"Unknown evaluation methods: {sorted(unknown)}")
    if "c4" in requested and not checkpoint:
        raise ValueError("C4 evaluation requires --checkpoint")
    validation = [row for row in rows if row["split"] == "validation"]
    test = [row for row in rows if row["split"] == "test"]
    aggregate_mode = (bool(rows)
                      and all(row.get("comparison_ids") for row in rows))

    embedding_by_id: dict[str, np.ndarray] = {}
    embedding_cache_status = "not supplied"
    embedding_meta = {}
    if embedding_path and embedding_path.is_file():
        meta_path = embedding_path.with_suffix(".json")
        embedding_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        expected_revision = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"
        is_mfcc26_cache = (embedding_meta.get("model") == "c3-mfcc26"
                           and embedding_meta.get("representation") == "mfcc26"
                           and embedding_meta.get("feature_dimension") == 26)
        is_clap_cache = (embedding_meta.get("model") == "laion/clap-htsat-unfused"
                         and embedding_meta.get("revision") == expected_revision)
        expected_cache_status = MARK if synthetic else "human_response"
        valid_meta = ((is_mfcc26_cache or is_clap_cache)
                      and embedding_meta.get("manifest_sha256") == _sha256(manifest_path)
                      and embedding_meta.get("data_status") == expected_cache_status)
        if valid_meta:
            with np.load(embedding_path, allow_pickle=False) as archive:
                ids = archive["sample_ids"].astype(str)
                vectors = np.asarray(archive["embeddings"], dtype=np.float32)
            if (vectors.ndim != 2 or len(ids) != vectors.shape[0] or len(set(ids)) != len(ids)
                    or not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) <= 1e-12)):
                raise ValueError("Embedding cache has duplicate IDs or invalid sample vectors")
            expected_dimension = 26 if is_mfcc26_cache else 512
            if vectors.shape[1] != expected_dimension:
                representation = "MFCC26" if is_mfcc26_cache else "CLAP"
                raise ValueError(f"{representation} cache must contain {expected_dimension}D vectors, "
                                 f"got {vectors.shape[1]}")
            embedding_by_id = {sid: vector for sid, vector in zip(ids, vectors)}
            representation_name = "mfcc26" if is_mfcc26_cache else "pinned CLAP"
            embedding_cache_status = f"validated {representation_name} cache: {len(ids)} embeddings"
        else:
            embedding_cache_status = "ignored: model, revision, or manifest hash does not match this run"
    elif embedding_path:
        embedding_cache_status = f"not found: {embedding_path}"

    adapted = None
    training_metadata = None
    if checkpoint:
        import torch
        checkpoint_state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if checkpoint_state.get("encoder_model") == "c3-mfcc26":
            adapted = MFCCAdaptedScorer(checkpoint,
                                        allow_synthetic_checkpoint=allow_synthetic and synthetic)

        else:
            adapted = AdaptedScorer(checkpoint,
                                    allow_synthetic_checkpoint=allow_synthetic and synthetic)

        if (adapted.encoder_model != "c3-mfcc26"
                and (adapted.encoder_model != "laion/clap-htsat-unfused"
                     or adapted.encoder_revision != "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a")):
            raise ValueError("Fair C4-versus-CLAP comparison requires the pinned laion/clap-htsat-unfused encoder revision")
        run_config_path = checkpoint.parent / "run_config.json"
        if not synthetic:
            if not run_config_path.is_file():
                raise ValueError("Human evaluation requires the training run_config.json beside the checkpoint")
            training_metadata = json.loads(run_config_path.read_text(encoding="utf-8"))
            expected_provenance = {
                "triplets_sha256": _sha256(split_path),
                "train_triplets_sha256": _split_rows_sha256(source_rows, "train"),
                "validation_triplets_sha256": _split_rows_sha256(source_rows, "validation"),
                "test_triplets_sha256": _split_rows_sha256(source_rows, "test"),
                "checkpoint_sha256": _sha256(checkpoint),
                "embedding_cache_sha256": _sha256(embedding_path) if embedding_path and embedding_path.is_file() else None,
                "encoder_model": adapted.encoder_model,
                "encoder_revision": adapted.encoder_revision,
                "training_split_name": "train",
                "checkpoint_selection_split": "validation",
                "test_labels_used_for_training_or_selection": False,
                "data_status": "human_response",
                "train_triplets": sum(row["split"] == "train" for row in rows),
                "validation_triplets": sum(row["split"] == "validation" for row in rows),
                "test_rows_present_but_not_used": len(test),
            }
            for field, expected in expected_provenance.items():
                if training_metadata.get(field) != expected:
                    raise ValueError(f"C4 training provenance mismatch for {field}: expected {expected!r}, "
                                     f"found {training_metadata.get(field)!r}")
        if embedding_meta and embedding_by_id:
            expected_representation = adapted.encoder_model
            if (embedding_meta.get("model") != expected_representation
                    or (not isinstance(adapted, MFCCAdaptedScorer)
                        and embedding_meta.get("revision") != adapted.clap_revision)):
                embedding_by_id = {}
                embedding_cache_status = "ignored: embedding cache encoder does not match the adapted C4 checkpoint"

    score_cache: dict[tuple[str, str, str], float] = {}

    def audio_path(sample_id: str) -> Path:
        entry = audio_by_id[sample_id].get("raw_audio_path") or audio_by_id[sample_id].get("audio_path")
        if not entry:
            raise ValueError(f"Manifest has no audio path for sample {sample_id}")
        candidate = Path(entry)
        candidate = candidate if candidate.is_absolute() else ROOT / candidate
        if not candidate.is_file():
            raise ValueError(f"Audio file does not exist for sample {sample_id}: {candidate}")
        return candidate

    def get_score(method: str, left: str, right: str) -> float:
        low, high = sorted((left, right))
        key = (method, low, high)
        if key in score_cache:
            return score_cache[key]
        if method == "synth_aware":
            score = score_similarity(None, None, method, reference_id=left,
                                     candidate_id=right, manifest_path=manifest_path)
        elif (method == "c4" and left in embedding_by_id and right in embedding_by_id
              and embedding_meta.get("model") == adapted.encoder_model):
            score = adapted.score_embeddings(embedding_by_id[left], embedding_by_id[right])
        elif (method == "clap" and left in embedding_by_id and right in embedding_by_id
              and embedding_meta.get("model") == "laion/clap-htsat-unfused"):
            similarity = float(np.clip(_cosine(embedding_by_id[left], embedding_by_id[right]), -1.0, 1.0))
            score = SimilarityResult("clap", similarity, 1.0 - similarity)
        else:
            left_path, right_path = audio_path(left), audio_path(right)
            if method == "c4":
                if isinstance(adapted, MFCCAdaptedScorer):
                    from generation.corpus_audio import load_audio
                    left_row, right_row = audio_by_id[left], audio_by_id[right]
                    if not left_row.get("audio_path") and left_row.get("raw_audio_path"):
                        left_path = load_audio(left_row, ROOT, verify=True)
                    if not right_row.get("audio_path") and right_row.get("raw_audio_path"):
                        right_path = load_audio(right_row, ROOT, verify=True)
                score = adapted.score(left_path, right_path)
            else:
                score = score_similarity(left_path, right_path, method,
                                         manifest_path=manifest_path,
                                         clap_model="laion/clap-htsat-unfused",
                                         clap_revision="8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a",
                                         clap_local_files_only=(method == "clap"))
        score_cache[key] = score.similarity
        return score.similarity

    method_failures: dict[str, str] = {}
    available: list[str] = []
    for method in requested:
        try:
            for row in validation + test:
                get_score(method, row["anchor_id"], row["positive_id"])
                get_score(method, row["anchor_id"], row["negative_id"])
            available.append(method)
        except Exception as error:
            method_failures[method] = f"{type(error).__name__}: {error}"
            for key in [key for key in score_cache if key[0] == method]:
                del score_cache[key]
    if not available:
        raise RuntimeError("No requested metric could score every validation and test comparison")

    def score_rows(target_rows: list[dict]) -> list[dict]:
        scored = []
        for row in target_rows:
            result = dict(row)
            for method in available:
                result[f"sim_{method}_positive"] = get_score(method, row["anchor_id"], row["positive_id"])
                result[f"sim_{method}_negative"] = get_score(method, row["anchor_id"], row["negative_id"])
                result[f"predicted_{method}_choice"] = (
                    "positive" if result[f"sim_{method}_positive"] > result[f"sim_{method}_negative"] + 1e-12
                    else "negative" if result[f"sim_{method}_negative"] > result[f"sim_{method}_positive"] + 1e-12
                    else "tie")
            scored.append(result)
        return scored

    # Baseline ranking and model selection use human validation labels only.
    validation_scored = score_rows(validation)
    test_scored = score_rows(test)
    baseline_methods = [method for method in available if method != "c4"]
    if synthetic:
        validation_summary = None
        selected_baseline = None
    elif aggregate_mode:
        validation_summary = {
            method: {"aggregate_comparison_accuracy": float(np.mean(_accuracy_values(validation_scored, method))),
                     "aggregate_comparisons": len(validation_scored)}
            for method in baseline_methods
        }
        selected_baseline = (max(baseline_methods,
                                 key=lambda method: validation_summary[method]["aggregate_comparison_accuracy"])
                             if baseline_methods else None)
    else:
        validation_summary = {
            method: {"participant_macro_accuracy": float(np.mean(list(
                _participant_accuracy(validation_scored, _accuracy_values(validation_scored, method)).values()))),
                     "responses": len(validation_scored)}
            for method in baseline_methods
        }
        selected_baseline = (max(baseline_methods,
                                 key=lambda method: validation_summary[method]["participant_macro_accuracy"])
                             if baseline_methods else None)

    output_dir.mkdir(parents=True, exist_ok=True)
    validation_path = output_dir / "validation_scored_comparisons.csv"
    test_path = output_dir / "test_scored_comparisons.csv"
    _write_rows(validation_path, validation_scored)
    _write_rows(test_path, test_scored)
    result = {
        "data_status": MARK if synthetic else "human_response",
        "synthetic_evidence": synthetic,
        "synthetic_results_are_evidence": False,
        "methods_requested": requested,
        "methods_computed_on_identical_validation_and_test_rows": available,
        "method_failures_or_unavailable": method_failures,
        "embedding_cache": embedding_cache_status,
        "clap_embedding_cache": embedding_cache_status,
        "baseline_availability": baseline_availability(),
        "split_integrity": split_integrity,
        "validation_rows": len(validation),
        "test_rows": len(test),
        "validation_scored_file": str(validation_path),
        "test_scored_file": str(test_path),
        "frozen_baseline_selected_on_validation": selected_baseline,
        "validation_baseline_performance": validation_summary,
        "test_metrics": None,
        "paired_test": None,
        "hard_case_results": None,
        "reproducibility": {
            "seed": seed,
            "bootstrap_draws": bootstrap_draws,
            "split_manifest_sha256": _sha256(split_path),
            "audio_manifest_sha256": _sha256(manifest_path),
            "checkpoint_sha256": _sha256(checkpoint) if checkpoint and checkpoint.is_file() else None,
            "training_run_config": str(checkpoint.parent / "run_config.json")
            if checkpoint and (checkpoint.parent / "run_config.json").is_file() else None,
            "training_run_config_sha256": _sha256(checkpoint.parent / "run_config.json")
            if checkpoint and (checkpoint.parent / "run_config.json").is_file() else None,
            "training_triplet_manifest_sha256": training_metadata.get("triplets_sha256") if training_metadata else None,
            "embedding_cache_sha256": _sha256(embedding_path) if embedding_path and embedding_path.is_file() else None,
            "test_rows_used_for_selection_or_tuning": False,
            "audio_preprocessing": (
                "C3 MFCC26: mono, 44.1 kHz, existing manifest/canonical audio policy; C3 MFCC extraction"
                if isinstance(adapted, MFCCAdaptedScorer) else
                "mono, 44.1 kHz, DC high-pass, fixed RMS target with peak ceiling"),
            "metric_tie_rule": "exact score tie within 1e-12 contributes 0.5 choice accuracy",
            "human_unit": ("one aggregated, unambiguous comparison; confidence is excluded upstream"
                           if aggregate_mode else
                           "individual decisive held-out response; uncertain responses are excluded upstream"),
            "software": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "numpy": _package_version("numpy"),
                "scipy": _package_version("scipy"),
                "torch": _package_version("torch"),
                "transformers": _package_version("transformers"),
                "soundfile": _package_version("soundfile"),
                "cdpam": _package_version("cdpam"),
            },
            "method_definitions": {
                "mfcc": "cosine over pooled MFCC 1-12 mean/std summaries",
                "stft": "cosine over one 2048-point pooled log-magnitude profile",
                "ms_stft": "mean cosine over pooled 512/1024/2048/4096-point profiles",
                "clap": "frozen laion/clap-htsat-unfused cosine",
                "c4": ("C3-compatible mfcc26 feature vector with trainable projection learned by triplet margin loss"
                       if isinstance(adapted, MFCCAdaptedScorer) else
                       "same frozen CLAP revision with trainable projection learned by triplet margin loss"),
                "cdpam": "published pretrained pairwise perceptual distance; lower is better",
                "synth_aware": "normalized Vital parameter-space distance; non-audio baseline",
            },
            "clap_encoder": {
                "model": "laion/clap-htsat-unfused",
                "revision": "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a",
            },
        },
        "note": ("Synthetic labels only exercise scoring and split integrity; accuracy, confidence intervals, "
                 "paired tests, and hard-case results are suppressed. Do not cite as perceptual evidence."
                 if synthetic else
                 "Test labels are used once for final reporting only. "
                 + ("Each aggregate comparison is treated as the independent preference observation. "
                    if aggregate_mode else "")
                 + "The adapted C4 scores the same validated representation used by its embedding cache."),
    }

    if not synthetic:
        summaries: dict[str, dict] = {}
        participant_values: dict[str, dict[str, float]] = {}
        for index, method in enumerate(available):
            summaries[method], participant_values[method] = _metric_summary(
                test_scored, method, bootstrap_draws, seed + index,
                aggregate_mode=aggregate_mode)
        result["test_metrics"] = summaries
        result["test_ranking_descriptive_only"] = sorted(
            available, key=lambda method: summaries[method]["triplet_choice_accuracy"], reverse=True)

        paired = {"strongest_frozen_baseline_selected_on_validation": selected_baseline,
                  "baseline_comparisons": {}}
        raw_p_values = {}
        if "c4" in participant_values:
            for index, method in enumerate(baseline_methods):
                c4_values = _accuracy_values(test_scored, "c4")
                base_values = _accuracy_values(test_scored, method)
                if aggregate_mode:
                    comparison = _paired_comparison_test(test_scored, c4_values, base_values)
                    comparison["audio_component_bootstrap_95_percent_ci_accuracy_difference"] = (
                        _audio_component_bootstrap_ci(test_scored, c4_values - base_values,
                                                      bootstrap_draws, seed + 1000 + index))
                    raw_p_values[method] = comparison["paired_sign_test_p_value"]
                else:
                    comparison = _paired_sign_test(participant_values["c4"], participant_values[method])
                    comparison["two_way_cluster_bootstrap_95_percent_ci_accuracy_difference"] = (
                        _two_way_bootstrap_ci(test_scored, c4_values - base_values,
                                              bootstrap_draws, seed + 1000 + index))
                    raw_p_values[method] = comparison["participant_level_paired_sign_test_p_value"]
                paired["baseline_comparisons"][method] = comparison
            adjusted = _holm_adjust(raw_p_values)
            for method, p_value in adjusted.items():
                paired["baseline_comparisons"][method]["holm_adjusted_p_value"] = p_value
            paired["test_scope"] = (
                "paired aggregate-comparison accuracy differences; sign test compares majority-vote comparisons; "
                "bootstrap resamples audio-disjoint components"
                if aggregate_mode else
                "paired per-participant accuracy differences; sign tests treat participants as independent clusters; "
                "two-way bootstrap resamples participants and audio-disjoint test components")
        else:
            paired["status"] = "C4 was unavailable; no adaptation comparison can be reported"
        result["paired_test"] = paired
        result["hard_case_results"] = (
            {"status": "not_applicable", "reason": "one majority-vote row per comparison; respondent-level consensus is not present"}
            if aggregate_mode else _triplet_hard_cases(test_scored, available))

    run_meta_path = output_dir / "benchmark_config.json"
    run_meta_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split_manifest", type=Path)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/raw/corpus_v4/manifest.csv")
    parser.add_argument("--checkpoint", type=Path,
                        help="Required for real human evaluation; synthetic checkpoint needs --allow-synthetic")
    parser.add_argument("--embeddings", type=Path,
                        default=ROOT / "c4_metric/outputs/embeddings/clap_corpus_v4.npz",
                        help="Matching pinned CLAP or mfcc26 cache; should cover survey IDs for reproducible scoring")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "c4_metric/outputs/evaluation")
    parser.add_argument("--methods", default=",".join(DEFAULT_METHODS),
                        help="Baselines: mfcc,ms_stft,clap,cdpam,synth_aware; c4 is added when a checkpoint is supplied")
    parser.add_argument("--bootstrap-draws", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.split_manifest, args.manifest, args.output_dir,
                              checkpoint=args.checkpoint,
                              methods=tuple(item.strip() for item in args.methods.split(",") if item.strip()),
                              bootstrap_draws=args.bootstrap_draws, seed=args.seed,
                              allow_synthetic=args.allow_synthetic,
                              embedding_path=args.embeddings), indent=2))


if __name__ == "__main__":
    main()
