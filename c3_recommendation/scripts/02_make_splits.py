"""Phase 2 - split the real parameter table into bank / val / test and freeze it.

Writes to ``<outputs_dir>/splits/``:
  split_manifest.parquet  (sample_id, split)
  split_summary.json      (counts, SHA-256 of sorted IDs per split, duplicate report, inputs)
  split_balance.csv       (per-parameter mean/std/quantiles per split, flags gaps > 0.02)

Once saved, the split is frozen: a re-run recomputes it and must reproduce the same hashes.
A different result is refused unless ``--overwrite`` is given.

Usage (repo root):
    python c3_recommendation/scripts/02_make_splits.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.config import load_config  # noqa: E402
from c3.data_sources import make_source  # noqa: E402
from c3.splits import (  # noqa: E402
    MANIFEST_NAME, SUMMARY_NAME, ids_sha256, make_splits, save_splits, split_balance,
)

BALANCE_THRESHOLD = 0.02
DUP_TOLERANCE = 1e-9


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--overwrite", action="store_true", help="replace a saved split that differs")
    args = parser.parse_args()

    cfg = load_config(args.config)
    out_dir = cfg.path("outputs_dir") / "splits"
    source = make_source(cfg)
    unit = source.params_unit()

    group_column = cfg.get("data.group_column")
    if group_column:
        raise SystemExit(f"group_column={group_column!r} is set, but no data source exposes groups yet")

    result = make_splits(unit, cfg["splits.val_fraction"], cfg["splits.test_fraction"], cfg.seed,
                         groups=None, dup_tol=DUP_TOLERANCE)
    again = make_splits(unit, cfg["splits.val_fraction"], cfg["splits.test_fraction"], cfg.seed,
                        groups=None, dup_tol=DUP_TOLERANCE)
    if again.hashes() != result.hashes():
        raise SystemExit("split is not reproducible within one run - investigate before saving")

    saved_summary = out_dir / SUMMARY_NAME
    status = "new"
    if saved_summary.exists():
        previous = json.loads(saved_summary.read_text(encoding="utf-8"))["sha256_sorted_ids"]
        if previous == result.hashes():
            status = "reproduced (identical to saved split)"
        elif not args.overwrite:
            raise SystemExit(f"saved split in {out_dir} has different hashes; refusing to overwrite "
                             "a frozen split (use --overwrite only if you mean to replace it)")
        else:
            status = "OVERWRITTEN (hashes changed)"

    save_splits(result, out_dir)
    summary = result.summary()
    summary.update({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": cfg["data.source"],
        "n_parameters": unit.shape[1],
        "duplicate_tolerance_max_abs_unit": DUP_TOLERANCE,
        "sha256_all_input_ids": ids_sha256(unit.index),
        "status": status,
    })
    saved_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    balance = split_balance(unit, result.manifest, threshold=BALANCE_THRESHOLD)
    balance.to_csv(out_dir / "split_balance.csv", index=False, float_format="%.6f")

    counts = result.counts()
    print(f"Data source: {cfg['data.source']}   samples: {len(unit)}   seed: {cfg.seed}")
    print(f"Counts: {counts}   grouping: {summary['grouping']}")
    print(f"Duplicate groups: {len(result.duplicate_groups)}   moved across splits: {len(result.duplicate_moves)}")
    for split, digest in result.hashes().items():
        print(f"  sha256[{split}] = {digest}")
    print(f"Status: {status}")
    gaps = balance.drop_duplicates("parameter").set_index("parameter")["max_mean_gap"]
    print(f"Largest split-mean gap per parameter (unit scale, flag > {BALANCE_THRESHOLD}):")
    for name, gap in gaps.items():
        print(f"  {name:20s} {gap:.4f}{'  <-- FLAG' if gap > BALANCE_THRESHOLD else ''}")
    print(f"Flagged parameters: {int((gaps > BALANCE_THRESHOLD).sum())}")
    print(f"Saved: {out_dir / MANIFEST_NAME}, {saved_summary.name}, split_balance.csv")


if __name__ == "__main__":
    main()
