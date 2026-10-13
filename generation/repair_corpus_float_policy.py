"""Guarded metadata migration for the first corpus runner's float-underflow bug.

Verifies EVERY saved raw file, processed waveform hash and parameter row before
changing recipe.json. Never modifies audio or checkpoint rows, and never renders.
Run --apply only after inspecting the report; default is verification only.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from generation import generate_corpus as runner
from generation.audio_processing import dc_filter
from generation.corpus_audio import PROCESSED_FLOAT_POLICY, canonical_float32, read_raw, sample_digest

LEGACY_SOURCES = {
    "generation/generate_corpus.py": "110e7663656827a2f64e62e6865d97cea4adb44a0fad111f5a89ff80cad4952f",
    "generation/corpus_audio.py": "64d35aca04560749c238442354e3c465f32b21ede12fa87a2fddb4e8a27f44ed",
}


def validate_transition(before, after):
    if before.get("runner_sources") != LEGACY_SOURCES or "processed_float32_policy" in before:
        raise ValueError("This migration accepts only the exact original single-master runner")
    expected = dict(after)
    expected.pop("processed_float32_policy", None)
    expected["runner_sources"] = before["runner_sources"]
    if before != expected or after.get("processed_float32_policy") != PROCESSED_FLOAT_POLICY:
        raise ValueError("Unrelated synthesis/runtime/storage change; migration refused")


def repair(count=131072, apply=False):
    with runner.exclusive_run():
        path = runner.OUTPUT / "recipe.json"
        before_bytes = path.read_bytes()
        before = json.loads(before_bytes)
        after = runner.recipe(count)
        validate_transition(before, after)
        g = runner.generator()
        samples = g.create_sobol_samples(count, len(g.PARAMS), g.SAMPLING_SEED)
        rows = []
        chunks = sorted((runner.OUTPUT / "chunks").glob("*.json"))
        for chunk_path in chunks:
            chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
            if not chunk or chunk_path.stem != f"{len(rows):06d}":
                raise ValueError("Checkpoint continuity failure")
            rows.extend(chunk)
        if not rows:
            raise ValueError("No saved rows; use a fresh runner instead")
        print(f"Verifying {len(rows):,} saved rows; no audio/checkpoint changes...", flush=True)
        runner.verify_rows(rows, samples, progress=True)
        print("PASS: every saved raw file, raw/processed sample hash and parameter value.", flush=True)
        affected = 0
        max_subnormal = 0.0
        for index, row in enumerate(rows):
            naive = dc_filter(read_raw(row, runner.ROOT), 44100).astype(np.float32)
            bits = naive.view(np.uint32)
            subnormal = ((bits & 0x7f800000) == 0) & ((bits & 0x007fffff) != 0)
            if sample_digest(naive) != row["processed_samples_sha256"]:
                if sample_digest(canonical_float32(naive)) != row["processed_samples_sha256"]:
                    raise ValueError("Difference extends beyond float32 subnormal handling")
                affected += 1
            if subnormal.any():
                max_subnormal = max(max_subnormal, float(np.max(abs(naive[subnormal].astype(np.float64)))))
            if (index + 1) % 2048 == 0:
                print(f"Audited float-underflow behavior: {index+1:,}/{len(rows):,}", flush=True)
        report = dict(verified_rows=len(rows), affected_old_reader_hashes=affected,
                      maximum_subnormal_amplitude=max_subnormal, before_recipe=before, after_recipe=after,
                      chunk_sha256={p.name: runner.sha(p) for p in chunks},
                      audio_or_checkpoint_modified=False, rendering_performed=False)
        print(f"PASS: {affected} old-reader hash discrepancies resolved by signed-zero handling only.", flush=True)
        if apply:
            audit_dir = runner.ROOT / "data/processed" / ("corpus_float_repair_" +
                        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            audit_dir.mkdir(parents=True, exist_ok=False)
            (audit_dir / "original_recipe.json").write_bytes(before_bytes)
            runner.atomic_json(audit_dir / "verification.json", report)
            if path.read_bytes() != before_bytes:
                raise ValueError("Recipe changed during verification; update refused")
            runner.atomic_json(path, after)
            print(f"Updated recipe fingerprints and explicit float policy. Backup/report: {audit_dir}", flush=True)
        else:
            print("Verification only. Use --apply to perform the backed-up recipe metadata migration.")
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=runner.count_value, default=131072)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repair(args.count, args.apply)
