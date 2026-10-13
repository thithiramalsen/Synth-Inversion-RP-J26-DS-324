"""Read-only v4 readiness check. Never calls the generation/render loop."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def storage_required(config, target, existing):
    """Two FLOAT WAVs per row, conservative header allowance, 10 GiB headroom."""
    frames = round(config["sample_rate"] * config["render_duration_seconds"])
    per_row = 2 * (frames * config["channels"] * 4 + 4096)
    remaining = max(0, target - existing)
    audio = remaining * per_row
    return audio, audio + (10 * GIB if remaining else 0)


def check(count, reference_config=None):
    if count <= 0 or count & (count - 1):
        raise ValueError("Target count must be a positive power of two")
    spec = importlib.util.spec_from_file_location(
        "frozen_dataset_generator", ROOT / "generation/scripts/05_generate_pilot_dataset.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    def forbidden(*args, **kwargs):
        raise RuntimeError("Rendering and dataset writes are disabled in preflight")

    for name in ("main", "render_sample", "save_manifests", "save_dataset_config",
                 "prepare_output_directories", "save_review_list"):
        setattr(generator, name, forbidden)
    generator.configure_profile("restricted_bend_sustain_v4")
    print("Read-only: checking preset, routing, environment and saved files...", flush=True)
    generator.validate_configuration()
    config = generator.build_dataset_config(count, list(generator.PARAMS))
    if reference_config:
        expected = json.loads(reference_config.read_text(encoding="utf-8"))
        ignored = {"created_utc", "sample_count"}
        changed = sorted(k for k in expected.keys() | config.keys()
                         if k not in ignored and expected.get(k) != config.get(k))
        if changed:
            raise ValueError(f"Reference configuration differs: {', '.join(changed)}")
    if generator.CONFIG_PATH.exists():
        if not generator.PILOT_MANIFEST_CSV.is_file():
            raise ValueError("Saved configuration exists without a CSV checkpoint; investigate first")
        samples = generator.create_sobol_samples(count, len(generator.PARAMS), generator.SAMPLING_SEED)
        rows = generator.load_resume_rows(config, samples)
        existing = len(rows)
        print(f"PASS: {existing:,} saved rows, raw/processed hashes, controls and Sobol prefix.")
    else:
        if any(p.exists() for p in (generator.PILOT_MANIFEST_CSV, generator.PILOT_MANIFEST_PARQUET)):
            raise ValueError("Manifest exists without configuration; investigate first")
        if generator.PILOT_AUDIO_DIR.exists() and any(generator.PILOT_AUDIO_DIR.rglob("*.wav")):
            raise ValueError("Audio exists without configuration; investigate first")
        if not reference_config:
            raise ValueError("Fresh reproduction requires --reference-config from the shared recipe")
        existing = 0
        print("PASS: fresh output location; configuration matches the shared reference.")
    destination = generator.PILOT_AUDIO_DIR.resolve()
    volume_path = destination
    while not volume_path.exists():
        volume_path = volume_path.parent
    free = shutil.disk_usage(volume_path).free
    audio, required = storage_required(config, count, existing)
    print(f"Output: {destination}")
    print(f"Target {count:,}; existing {existing:,}; additional {count - existing:,}.")
    print(f"Additional audio estimate: {audio / GIB:.1f} GiB; "
          f"with working headroom: {required / GIB:.1f} GiB; free: {free / GIB:.1f} GiB.")
    if free < required:
        print("NOT READY: insufficient storage. Nothing was rendered or changed.")
        return 2
    print("PASS: technical preflight. No rendering/writes. Cross-PC audio equality still needs verification.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=131072)
    parser.add_argument("--reference-config", type=Path)
    args = parser.parse_args()
    try:
        raise SystemExit(check(args.count, args.reference_config))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(1, f"NOT READY: {exc}\n")
