"""Compare local parameter labels with shared reference labels, without audio.

Works against a completed CSV/Parquet manifest or JSON checkpoints while rendering.
A matching prefix verifies only completed rows, not future audio or waveform equality.
"""
import argparse
import json
from pathlib import Path
import pandas as pd


def load_local(manifest=None, checkpoints=None):
    if manifest is not None:
        if manifest.suffix == ".parquet":
            return pd.read_parquet(manifest)
        headers = pd.read_csv(manifest, nrows=0).columns
        return pd.read_csv(manifest, float_precision="round_trip",
                           dtype={name: str for name in headers if name.endswith("_display")})
    rows = []
    for path in sorted(checkpoints.glob("*.json")):
        chunk = json.loads(path.read_text(encoding="utf-8"))
        if not chunk or path.stem != f"{len(rows):06d}":
            raise ValueError("Checkpoint filenames are not a contiguous prefix")
        rows.extend(chunk)
    return pd.DataFrame(rows)


def compare(reference, local):
    if not len(local):
        raise ValueError("No completed parameter rows to compare")
    if len(local) > len(reference):
        raise ValueError("Local dataset is larger than the reference")
    columns = list(reference.columns)
    if columns[:2] != ["sample_id", "sample_index"]:
        raise ValueError("Reference must start with sample_id and sample_index")
    missing = set(columns) - set(local.columns)
    if missing:
        raise ValueError(f"Local records missing columns: {sorted(missing)}")
    for frame, name in ((reference, "reference"), (local, "local")):
        if frame["sample_id"].duplicated().any() or list(frame["sample_index"]) != list(range(len(frame))):
            raise ValueError(f"{name} records are not a contiguous ordered prefix")
    try:
        pd.testing.assert_frame_equal(reference.iloc[:len(local)].reset_index(drop=True),
                                      local[columns].reset_index(drop=True),
                                      check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError(f"Parameter labels differ: {str(exc)[:700]}") from exc
    print(f"PASS: all {len(local):,} completed rows match the shared parameter reference exactly.")
    if len(local) < len(reference):
        print(f"Prefix only: {len(reference)-len(local):,} reference rows remain. Audio is not checked here.")
    else:
        print("Complete parameter table matches. Verify waveform equality separately.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--checkpoints", type=Path)
    args = parser.parse_args()
    compare(pd.read_parquet(args.reference), load_local(args.manifest, args.checkpoints))
