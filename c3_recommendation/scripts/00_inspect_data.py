"""Phase 0 - read-only inspection of the v4 parameter reference and corpus folder.

Reads the reference parameter tables and JSONs, lists (but never opens) the files
in the corpus folder while generation is running, and writes everything to
``c3_recommendation/outputs/v4/phase0_inspection.json``.

Nothing under ``reference/`` or the corpus folder is written, moved or deleted.

Usage (from the repository root):

    python c3_recommendation/scripts/00_inspect_data.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_DIR = REPO_ROOT / "reference"
DEFAULT_CORPUS_DIR = REPO_ROOT / "data" / "raw" / "corpus_v4"
DEFAULT_OUTPUT = REPO_ROOT / "c3_recommendation" / "outputs" / "v4" / "phase0_inspection.json"
CONFIG_NAME = "restricted_bend_sustain_v4_config.json"

ARRAY_LIMIT = 50
LEAKAGE_KEYWORDS = (
    "group", "family", "anchor", "parent", "sibling", "perturb", "sobol", "chunk", "seed", "batch",
)
# Columns per parameter in parameters_full.parquet, discovered in Phase 0.
PARAM_SUFFIXES = ("sample_01", "normalized", "raw", "display")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def truncate(value, limit: int = ARRAY_LIMIT):
    """Return a JSON-safe copy with long lists/dicts cut to ``limit`` items."""
    if isinstance(value, list):
        items = [truncate(item, limit) for item in value[:limit]]
        if len(value) > limit:
            items.append(f"... truncated, total length {len(value)}")
        return items
    if isinstance(value, dict):
        keys = list(value)
        out = {key: truncate(value[key], limit) for key in keys[:limit]}
        if len(keys) > limit:
            out["__truncated__"] = f"showing {limit} of {len(keys)} keys"
        return out
    return value


def to_jsonable(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def describe_table(df: pd.DataFrame, id_column: str, value_columns: list[str]) -> dict:
    numeric = df.select_dtypes(include="number")
    return {
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "null_counts": {col: int(n) for col, n in df.isna().sum().items()},
        "numeric_stats": {
            col: {"min": numeric[col].min(), "max": numeric[col].max(), "mean": numeric[col].mean()}
            for col in numeric.columns
        },
        "head": df.head(5).astype(str).to_dict(orient="records"),
        "duplicated_ids": int(df[id_column].duplicated().sum()),
        "duplicated_parameter_rows": int(df.duplicated(subset=value_columns).sum()),
    }


def inspect_reference_jsons(reference_dir: Path) -> dict:
    out = {}
    for path in sorted(reference_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            content = json.load(handle)
        out[path.name] = {
            "bytes": path.stat().st_size,
            "top_level_type": type(content).__name__,
            "top_level_length": len(content) if hasattr(content, "__len__") else None,
            "content": truncate(content),
        }
    return out


def verify_artifact_hashes(reference_dir: Path) -> dict:
    """Recompute SHA-256 of reference files and compare with the recorded values."""
    expected: dict[str, str] = {}
    integrity = reference_dir / "clone_integrity.json"
    if integrity.exists():
        recipe = json.loads(integrity.read_text(encoding="utf-8")).get("files", {}).get("recipe", {})
        for rel, digest in recipe.items():
            if rel.startswith("reference/"):
                expected[rel.split("/", 1)[1]] = digest
    verification = reference_dir / "corpus_verification.json"
    if verification.exists():
        for name, meta in json.loads(verification.read_text(encoding="utf-8")).get("artifacts", {}).items():
            expected.setdefault(name, meta["sha256"])
    results = {}
    for name, digest in sorted(expected.items()):
        path = reference_dir / name
        actual = sha256_file(path) if path.exists() else None
        results[name] = {"expected": digest, "actual": actual, "match": actual == digest}
    return results


def list_corpus(corpus_dir: Path) -> dict:
    """File metadata only - honours the rule not to read corpus data during generation."""
    out = {
        "path": str(corpus_dir),
        "exists": corpus_dir.exists(),
        "run_lock_present": (corpus_dir / ".run.lock").exists(),
    }
    if not corpus_dir.exists():
        return out
    recipe = corpus_dir / "recipe.json"
    if recipe.exists():
        out["recipe.json"] = truncate(json.loads(recipe.read_text(encoding="utf-8")))
    for sub in ("chunks", "raw_float"):
        folder = corpus_dir / sub
        if not folder.exists():
            out[sub] = {"exists": False}
            continue
        names, total_bytes, extensions = [], 0, {}
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file():
                    names.append(entry.name)
                    total_bytes += entry.stat().st_size
                    ext = Path(entry.name).suffix
                    extensions[ext] = extensions.get(ext, 0) + 1
        names.sort()
        out[sub] = {
            "file_count": len(names),
            "total_bytes": total_bytes,
            "extensions": extensions,
            "first_names": names[:10],
            "last_names": names[-10:],
        }
    return out


def extract_schema(config: dict) -> dict:
    order = config["parameter_order"]
    params = config["parameters"]
    return {
        "dataset_name": config.get("dataset_name"),
        "schema_status": config.get("schema_status"),
        "parameter_order": order,
        "parameters": {
            name: {
                "control": params[name].get("control"),
                "mode": params[name].get("mode"),
                "min": params[name]["min"],
                "max": params[name]["max"],
                # Every control in the v4 config is a continuous slider with a min/max interval.
                "type": "continuous" if "min" in params[name] and "max" in params[name] else "unknown",
            }
            for name in order
        },
        "fixed_controls_count": len(config.get("fixed_controls", {})),
        "modulations": config.get("modulations"),
        "sample_rate": config.get("sample_rate"),
        "channels": config.get("channels"),
        "midi_note": config.get("midi_note"),
        "velocity": config.get("velocity"),
        "note_duration_seconds": config.get("note_duration_seconds"),
        "render_duration_seconds": config.get("render_duration_seconds"),
        "sampling_method": config.get("sampling_method"),
        "sampling_seed": config.get("sampling_seed"),
        "sample_count_in_config": config.get("sample_count"),
        "audio_policy_id": config.get("audio_policy_id"),
    }


def verify_normalisation(full: pd.DataFrame, norm: pd.DataFrame, schema: dict) -> dict:
    """Check how the columns of each parameter relate to the config range."""
    out = {}
    for name in schema["parameter_order"]:
        lo, hi = schema["parameters"][name]["min"], schema["parameters"][name]["max"]
        unit = full[f"{name}_sample_01"].to_numpy()
        vital = full[f"{name}_normalized"].to_numpy()
        raw = full[f"{name}_raw"].to_numpy()
        recomputed_unit = (vital - lo) / (hi - lo)
        order = np.argsort(vital, kind="stable")
        out[name] = {
            "range": [lo, hi],
            "sample_01_min_max": [float(unit.min()), float(unit.max())],
            "normalized_min_max": [float(vital.min()), float(vital.max())],
            "normalized_within_config_range": bool((vital >= lo - 1e-6).all() and (vital <= hi + 1e-6).all()),
            "max_abs_err_unit_recomputed_vs_sample_01": float(np.abs(recomputed_unit - unit).max()),
            "max_abs_err_normalized_vs_lo_plus_sample01_span": float(np.abs(lo + unit * (hi - lo) - vital).max()),
            "normalized_parquet_equals_full_normalized": bool(
                np.array_equal(norm[f"{name}_normalized"].to_numpy(), vital)
            ),
            "raw_equals_normalized": bool(np.allclose(raw, vital, rtol=0, atol=1e-12)),
            "raw_monotonic_in_normalized": bool((np.diff(raw[order]) >= -1e-9).all()),
            "normalized_is_float32_exact": bool(np.array_equal(vital.astype(np.float32).astype(np.float64), vital)),
        }
    return out


def inspect_structure(full: pd.DataFrame, id_column: str) -> dict:
    keyword_hits = [c for c in full.columns if any(k in c.lower() for k in LEAKAGE_KEYWORDS)]
    pattern = re.compile(r"^(?P<prefix>.+)_(?P<num>\d+)$")
    parsed = full[id_column].str.extract(pattern)
    id_numbers = pd.to_numeric(parsed["num"], errors="coerce")
    return {
        "leakage_keyword_columns": keyword_hits,
        "id_prefixes": sorted(parsed["prefix"].dropna().unique().tolist()),
        "id_number_width": sorted(parsed["num"].dropna().str.len().unique().tolist()),
        "id_suffix_equals_sample_index": bool((id_numbers == full["sample_index"]).all()),
        "sample_index_is_0_to_n_minus_1": bool(
            np.array_equal(full["sample_index"].to_numpy(), np.arange(len(full)))
        ),
        "is_sorted_by_sample_index": bool(full["sample_index"].is_monotonic_increasing),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-hashes", action="store_true", help="skip SHA-256 verification of reference files")
    args = parser.parse_args()

    reference_dir = args.reference_dir.resolve()
    config = json.loads((reference_dir / CONFIG_NAME).read_text(encoding="utf-8"))
    schema = extract_schema(config)
    names = schema["parameter_order"]
    id_column = "sample_id"

    full = pd.read_parquet(reference_dir / "parameters_full.parquet")
    norm = pd.read_parquet(reference_dir / "parameters_normalized.parquet")

    expected_full = [id_column, "sample_index"] + [f"{n}_{s}" for n in names for s in PARAM_SUFFIXES]
    expected_norm = [id_column, "sample_index"] + [f"{n}_normalized" for n in names]
    norm_cols = [f"{n}_normalized" for n in names]

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "paths": {"reference_dir": str(reference_dir), "corpus_dir": str(args.corpus_dir.resolve())},
        "schema": schema,
        "tables": {
            "parameters_full.parquet": describe_table(full, id_column, norm_cols),
            "parameters_normalized.parquet": describe_table(norm, id_column, norm_cols),
        },
        "table_consistency": {
            "full_columns_match_expected_layout": list(full.columns) == expected_full,
            "normalized_columns_match_expected_layout": list(norm.columns) == expected_norm,
            "same_row_count": len(full) == len(norm),
            "same_id_order": bool((full[id_column].to_numpy() == norm[id_column].to_numpy()).all()),
            "same_sample_index": bool(np.array_equal(full["sample_index"], norm["sample_index"])),
            "duplicated_unit_rows": int(full.duplicated(subset=[f"{n}_sample_01" for n in names]).sum()),
        },
        "normalisation": verify_normalisation(full, norm, schema),
        "structure": inspect_structure(full, id_column),
        "reference_jsons": inspect_reference_jsons(reference_dir),
        "reference_hashes": {} if args.skip_hashes else verify_artifact_hashes(reference_dir),
        "corpus": list_corpus(args.corpus_dir.resolve()),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(to_jsonable(report), indent=2, default=str), encoding="utf-8")

    # Console exit check.
    nrm = report["normalisation"]
    print(f"Samples: {len(full)}   Parameters: {len(names)}")
    print("Parameter names:", ", ".join(names))
    types = [p["type"] for p in schema["parameters"].values()]
    print(f"Continuous: {types.count('continuous')}   Categorical: {len(types) - types.count('continuous')}")
    print("Table consistency:", report["table_consistency"])
    print("Max |(normalized-min)/(max-min) - sample_01| per parameter:")
    for name in names:
        r = nrm[name]
        print(f"  {name:20s} {r['max_abs_err_unit_recomputed_vs_sample_01']:.3e}"
              f"  in_range={r['normalized_within_config_range']}  raw==norm={r['raw_equals_normalized']}"
              f"  raw_monotonic={r['raw_monotonic_in_normalized']}  float32={r['normalized_is_float32_exact']}")
    print("Structure:", report["structure"])
    if report["reference_hashes"]:
        bad = [n for n, r in report["reference_hashes"].items() if not r["match"]]
        print(f"Reference hashes: {len(report['reference_hashes']) - len(bad)} match, mismatches: {bad}")
    corpus = report["corpus"]
    print(f"Corpus run lock present: {corpus.get('run_lock_present')}   "
          f"chunks: {corpus.get('chunks', {}).get('file_count')}   "
          f"raw_float: {corpus.get('raw_float', {}).get('file_count')}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
