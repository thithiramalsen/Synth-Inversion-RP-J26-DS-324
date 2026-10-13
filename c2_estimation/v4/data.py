"""Validate v4 readbacks and freeze error-independent experimental assignments."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREPARED = ROOT / "data/processed/c2_v4/protocol_v1"
NAMES = (
    "wave_frame", "bend_amount", "filter_cutoff", "filter_resonance",
    "filter_drive", "amp_attack", "amp_decay", "amp_sustain", "amp_release",
    "filter_env_amount", "filter_env_attack", "filter_env_decay", "filter_env_sustain",
)
SEED = 20261013
COUNTS = {"train": 98304, "calibration": 16384, "validation": 8192, "test": 8192}
DIAGNOSTIC_COUNTS = {"train": 128, "calibration": 2048, "validation": 512, "test": 1024}
AUDIO_COLUMNS = ["raw_audio_path", "audio_policy_id", "raw_samples_sha256",
                 "processed_samples_sha256"]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def bounds(recipe: dict) -> tuple[np.ndarray, np.ndarray]:
    synthesis = recipe["synthesis"]
    if tuple(synthesis["parameter_order"]) != NAMES:
        raise ValueError("Expected the exact frozen 13-control order")
    lower = np.array([synthesis["parameters"][n]["min"] for n in NAMES], dtype=np.float64)
    upper = np.array([synthesis["parameters"][n]["max"] for n in NAMES], dtype=np.float64)
    if not np.isfinite([lower, upper]).all() or np.any(upper <= lower):
        raise ValueError("Invalid research bounds")
    return lower, upper


def to_z(values: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    z = (values - lower) / (upper - lower)
    # Preserve readbacks, including tiny floating-point excursions; never silently clip labels.
    if not np.isfinite(z).all() or np.any(z < -2e-6) or np.any(z > 1 + 2e-6):
        raise ValueError("Readback is outside the restricted research interval")
    return z


def from_z(z: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=np.float64)
    if not np.isfinite(z).all() or np.any(z < 0) or np.any(z > 1):
        raise ValueError("Predicted/perturbed research coordinates must be in [0, 1]")
    return lower + z * (upper - lower)


def assignments(count: int, *, seed: int = SEED, counts: dict | None = None,
                prefix_count: int = 1024, diagnostic_counts: dict | None = None) -> pd.DataFrame:
    counts = COUNTS if counts is None else counts
    diagnostic_counts = DIAGNOSTIC_COUNTS if diagnostic_counts is None else diagnostic_counts
    if set(counts) != set(COUNTS) or sum(counts.values()) != count:
        raise ValueError("Four disjoint split sizes must sum to the sample count")
    if not 0 <= prefix_count <= counts["train"] or counts["validation"] % 2:
        raise ValueError("Invalid development prefix or odd validation count")
    # The already studied v4 pilot is training-only. All remaining assignments are random.
    rng = np.random.default_rng(seed)
    remaining = rng.permutation(np.arange(prefix_count, count))
    splits = np.full(count, "train", dtype="<U11")
    offset = counts["train"] - prefix_count
    for name in ("calibration", "validation", "test"):
        splits[remaining[offset:offset + counts[name]]] = name
        offset += counts[name]
    roles = np.full(count, "", dtype="<U11")
    val = rng.permutation(np.flatnonzero(splits == "validation"))
    roles[val[:len(val) // 2]] = "inverse"
    roles[val[len(val) // 2:]] = "reliability"
    rank = np.full(count, -1, dtype=np.int64)
    diagnostic_rank = np.full(count, -1, dtype=np.int64)
    subset_rng = np.random.default_rng(seed + 1)
    for name in counts:
        eligible = np.flatnonzero(splits == name)
        ordered = subset_rng.permutation(eligible)
        rank[ordered] = np.arange(len(ordered))
        diagnostic_pool = ordered[roles[ordered] == "reliability"] if name == "validation" else ordered
        wanted = diagnostic_counts[name]
        if not 0 <= wanted <= len(diagnostic_pool):
            raise ValueError("Diagnostic subset is larger than its eligible partition")
        diagnostic_rank[diagnostic_pool[:wanted]] = np.arange(wanted)
    return pd.DataFrame({"split": splits, "validation_role": roles,
                         "selection_rank": rank, "diagnostic_rank": diagnostic_rank})


def validate_frame(frame: pd.DataFrame, recipe: dict, expected_count: int = 131072) -> dict:
    if len(frame) != expected_count:
        raise ValueError(f"Expected {expected_count} rows, got {len(frame)}")
    if frame.sample_id.duplicated().any() or frame.sample_index.duplicated().any():
        raise ValueError("Duplicate sample ID/index")
    if not np.array_equal(frame.sample_index, np.arange(expected_count)):
        raise ValueError("Manifest must be sorted with contiguous zero-based indexes")
    if frame[AUDIO_COLUMNS].isna().any().any() or frame.raw_audio_path.duplicated().any():
        raise ValueError("Missing audio metadata or duplicate master path")
    if not (frame.audio_policy_id == "dc_highpass_10hz_v1").all():
        raise ValueError("Wrong audio conditioning policy")
    columns = [n + "_normalized" for n in NAMES]
    actual_columns = [c for c in frame if c.endswith("_normalized")]
    if set(actual_columns) != set(columns):
        raise ValueError("Expected exactly 13 normalized controls")
    lower, upper = bounds(recipe)
    z = to_z(frame[columns].to_numpy(), lower, upper)
    if frame[columns].duplicated().any():
        raise ValueError("Duplicate complete parameter vectors")
    return {"rows": len(frame), "parameter_count": len(NAMES),
            "duplicate_vectors": 0, "z_min": z.min(axis=0).tolist(),
            "z_max": z.max(axis=0).tolist()}


def prepare(output: Path = DEFAULT_PREPARED, *, seed: int = SEED) -> dict:
    manifest = ROOT / "data/raw/corpus_v4/manifest.parquet"
    recipe_path = ROOT / "data/raw/corpus_v4/recipe.json"
    reference = ROOT / "data/processed/team_handoff_v4_131072/parameters_full.parquet"
    sources = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p)
               for p in (manifest, recipe_path, reference)}
    if (output / "protocol.json").exists():
        metadata, _ = load_prepared(output)
        if metadata["sources"] != sources or metadata["seed"] != seed:
            raise ValueError("Existing protocol differs; use a NEW output directory")
        print("Verified existing immutable protocol", output, flush=True)
        return metadata
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite a nonempty/incomplete protocol directory")
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    columns = ["sample_id", "sample_index", *AUDIO_COLUMNS, *[n + "_normalized" for n in NAMES]]
    frame = pd.read_parquet(manifest, columns=columns).sort_values("sample_index").reset_index(drop=True)
    audit = validate_frame(frame, recipe)
    reference_frame = pd.read_parquet(reference, columns=["sample_id", "sample_index", *columns[6:]])
    reference_frame = reference_frame.sort_values("sample_index").reset_index(drop=True)
    if not frame[reference_frame.columns].equals(reference_frame):
        raise ValueError("Canonical manifest and parameter reference do not agree exactly")
    lower, upper = bounds(recipe)
    z = to_z(frame[[n + "_normalized" for n in NAMES]].to_numpy(), lower, upper)
    for j, name in enumerate(NAMES):
        frame[name + "_z"] = z[:, j]
    frame = pd.concat([frame, assignments(len(frame), seed=seed)], axis=1)
    output.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output / "manifest.parquet", index=False)
    split_columns = ["sample_id", "sample_index", "split", "validation_role", "selection_rank", "diagnostic_rank"]
    frame[split_columns].to_csv(output / "split_manifest.csv", index=False, lineterminator="\n")
    metadata = {
        "protocol_version": "c2_v4_v1", "seed": seed, "sources": sources,
        "parameter_names": list(NAMES), "lower": lower.tolist(), "upper": upper.tolist(),
        "coordinate": "z=(actual_recorded_vital_normalized-lower)/(upper-lower)",
        "split_counts": COUNTS, "validation_roles": {"inverse": 4096, "reliability": 4096},
        "development_prefix_training_only": 1024, "diagnostic_counts": DIAGNOSTIC_COUNTS,
        "selection_policy": "seeded before model/error/uncertainty inspection",
        "delta_z": .02, "delta_z_validation_candidates": [.01, .02, .05],
        "tau_z": .05, "tau_z_sensitivity": [.025, .05, .10],
        "test_policy": "IDs reserved only; no test feature extraction, training, tuning or evaluation yet",
        "audit": audit, "recipe": recipe,
        "manifest_sha256": sha(output / "manifest.parquet"),
        "split_sha256": sha(output / "split_manifest.csv"),
    }
    write_json(output / "protocol.json", metadata)
    print(json.dumps({"prepared": str(output), "audit": audit, "splits": COUNTS}), flush=True)
    return metadata


def load_prepared(path: Path) -> tuple[dict, pd.DataFrame]:
    meta = json.loads((path / "protocol.json").read_text(encoding="utf-8"))
    if sha(path / "manifest.parquet") != meta["manifest_sha256"] or sha(path / "split_manifest.csv") != meta["split_sha256"]:
        raise ValueError("Prepared manifest/split changed after freezing")
    return meta, pd.read_parquet(path / "manifest.parquet")


def inverse_rows(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope not in ("development", "full"):
        raise ValueError("Scope must be development or full")
    train = frame[frame.split == "train"].sort_values("selection_rank")
    validation = frame[(frame.split == "validation") & (frame.validation_role == "inverse")].sort_values("selection_rank")
    if scope == "development":
        train, validation = train.iloc[:4096], validation.iloc[:512]
    return pd.concat([train, validation]).sort_values("sample_index").reset_index(drop=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    prepare(args.output, seed=args.seed)
