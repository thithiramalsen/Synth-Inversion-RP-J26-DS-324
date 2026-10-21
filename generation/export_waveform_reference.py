"""Export portable waveform hashes for an existing corpus; never render audio."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from generation.verify_reproduction import waveform_digest

ROOT = Path(__file__).resolve().parents[1]


def export(output):
    manifest = ROOT / "data/manifests/restricted_bend_sustain_v4.csv"
    config_path = manifest.with_name("restricted_bend_sustain_v4_config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    files = {}
    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != config["sample_count"]:
        raise ValueError("Corpus is incomplete; finish generation and run preflight first")
    for index, row in enumerate(rows):
        expected_id = f"restricted_bend_sustain_v4_{index:05d}"
        if row["sample_id"] != expected_id or int(row["sample_index"]) != index:
            raise ValueError("Manifest is not a contiguous ordered corpus")
        for column, checksum in (("audio_path", "audio_sha256"), ("raw_audio_path", "raw_audio_sha256")):
            relative = row[column].replace("\\", "/")
            path = (ROOT / relative).resolve()
            if not path.is_relative_to(ROOT):
                raise ValueError("Audio path outside repository")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row[checksum]:
                raise ValueError(f"Local manifest checksum mismatch: {relative}")
            files[relative] = waveform_digest(path)
        if (index + 1) % 1024 == 0:
            print(f"Hashed {index + 1:,}/{len(rows):,} rows", flush=True)
    # Compatible with verify_reproduction.py; recipe/environment checked by preflight.
    payload = {"dataset": config["dataset_name"], "count": len(rows),
               "note": "Waveforms only; separately verify frozen recipe/environment with preflight.",
               "files": {"recipe": {}, "candidates": files, "pilot": {}}}
    with output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print(f"Saved {output}; share this small reference instead of the WAV corpus.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.output)
