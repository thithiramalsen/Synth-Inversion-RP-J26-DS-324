"""Demo - show that the held-out test split is locked (rule R6). Read-only.

Usage (repo root):
    python c3_recommendation/scripts/demo_test_lock.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.config import load_config  # noqa: E402
from c3.splits import BANK, TEST, VAL, Splits, TestSplitLocked, load_manifest  # noqa: E402


def main() -> None:
    cfg = load_config()
    splits = Splits.from_config(cfg, load_manifest(cfg.path("outputs_dir") / "splits"))
    print(f"bank (candidates):   {len(splits.ids(BANK)):,} sounds - readable")
    print(f"val (tuning):        {len(splits.ids(VAL)):,} sounds - readable")
    try:
        splits.get_targets(TEST, 5, cfg.seed)
        print("test (final exam):   UNLOCKED - final_test.enabled is true and PREREGISTRATION.md exists")
    except TestSplitLocked as error:
        print(f"test (final exam):   LOCKED -> {error}")


if __name__ == "__main__":
    main()
