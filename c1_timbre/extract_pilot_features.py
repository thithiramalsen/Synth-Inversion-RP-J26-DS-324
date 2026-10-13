"""Extract features from the exact versioned, level-controlled pilot signal.

No filtering/gain is applied here. Historical eight-control analysis is unchanged.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import soundfile as sf

from c1_timbre.feature_extraction import extract_features


def extract_bundle(bundle_path: Path, output: Path):
    if output.exists():
        raise FileExistsError("Feature output exists; use a new output path")
    payload = bundle_path.read_bytes()
    bundle = json.loads(payload)
    bundle_hash = hashlib.sha256(payload).hexdigest()
    primary_ids = sorted({t["sample_id"] for a in bundle["assignments"] for t in a["trials"] if t["kind"] == "primary"})
    rows = []
    for sample_id in primary_ids:
        sample = bundle["samples"][sample_id]
        path = (bundle_path.parent / sample["feature_path"]).resolve()
        if not path.is_relative_to(bundle_path.resolve().parent):
            raise ValueError("Feature audio is outside the bundle")
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample["feature_sha256"]:
            raise ValueError("Feature audio hash mismatch")
        audio, rate = sf.read(path, dtype="float64")
        if rate != 44100 or audio.ndim != 1:
            raise ValueError("Invalid canonical feature input")
        rows.append(dict(study_id=bundle["study_id"], rehearsal=bundle["rehearsal"], sample_id=sample_id,
                         source_sample_id=sample["source_sample_id"], bundle_sha256=bundle_hash,
                         audio_sha256=sample["feature_sha256"], audio_policy_ids="+".join(sample["policy_ids"]),
                         gain=sample["gain"], filter_cutoff_normalized=sample["parameters"]["filter_cutoff"],
                         **extract_features(audio, rate, 2048, 512)))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(f"Wrote {extract_bundle(args.bundle.resolve(), args.output.resolve())} feature rows")
