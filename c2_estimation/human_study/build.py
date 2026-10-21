"""Export nine fixed non-test pairs, frozen q, and an auditable private manifest."""
import os
for _key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[_key] = "1"

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from c2_estimation.human_study.design import VERSION, SEED, NAMES, LABELS, select_cases, assignment
from c2_estimation.v4.audit_results import DEFAULT_DEVELOPMENT, read_results
from c2_estimation.v4.build_viewer import save_playback
from c2_estimation.v4.data import ROOT, DEFAULT_PREPARED, load_prepared, sha, write_json
from c2_estimation.v4.diagnostics import Renderer, distance
from c2_estimation.v4.stability import checked_case
from generation.corpus_audio import load_audio, sample_digest

DEFAULT_BUNDLE = ROOT / "data/processed/c2_v4/human_study_bundle_v1"


def build(output, prepared=DEFAULT_PREPARED, development=DEFAULT_DEVELOPMENT):
    if output.exists():
        raise ValueError("Use a new output directory; existing study bundles are never overwritten")
    protocol, source = load_prepared(prepared)
    frame, _, probabilities, _, calibrators = read_results(development)
    if tuple(protocol["parameter_names"]) != NAMES:
        raise ValueError("Unexpected parameter order")
    if calibrators["diagnostic_config"]["protocol_sha256"] != sha(prepared / "protocol.json"):
        raise ValueError("Protocol differs from frozen diagnostics")
    for path, checksum in calibrators["diagnostic_config"]["sources"].items():
        if sha(ROOT / path) != checksum:
            raise ValueError("Frozen diagnostic source changed: " + path)
    chosen = select_cases(frame)
    diagnostic = development / "diagnostics_reliability-validation"
    config = json.loads((diagnostic / "run_config.json").read_text())
    summary = json.loads((diagnostic / "summary.json").read_text())
    renderer = Renderer(protocol["recipe"])
    (output / "audio").mkdir(parents=True)
    cases, provenance = [], []
    for row in chosen.itertuples(index=False):
        rank = int(row.diagnostic_rank)
        case_id = "practice" if rank == 8 else f"case_{rank + 1:02d}"
        original = source[source.sample_id == row.sample_id].iloc[0].to_dict()
        if original["split"] != "validation" or original["validation_role"] != "reliability":
            raise ValueError("Attempted access to an unapproved partition")
        saved = checked_case(diagnostic / "cases" / (row.sample_id + ".json"), config["signature"],
                             row.sample_id, summary["case_checksums"][row.sample_id + ".json"])
        target, rate = load_audio(original, ROOT, verify=True)
        z = np.array([getattr(row, name + "_predicted_z") for name in NAMES])
        rendered, _ = renderer.render(z)
        if rate != 44100 or sample_digest(target) != saved["target_sha256"] or sample_digest(rendered) != saved["rendered_sha256"]:
            raise ValueError("Audio differs from frozen diagnostic; stop, do not choose a nicer clip")
        if not np.isclose(distance(target, rendered), row.R, rtol=0, atol=1e-10):
            raise ValueError("Reconstruction distance differs from frozen result")
        audio = {}
        for label, samples in (("target", target), ("predicted", rendered)):
            if np.max(np.abs(samples)) == 0:
                raise ValueError("Digital silence: review and version the technical QA decision")
            audio[label] = save_playback(output / "audio" / f"{case_id}_{label}.wav", samples)
        q = probabilities["g(U,S,R)"][frame.index[frame.sample_id == row.sample_id][0]]
        cases.append({"case_id": case_id, "parameters": [
            {"name": name, "label": label, "predicted_z": float(z[j]), "q": float(q[j])}
            for j, (name, label) in enumerate(zip(NAMES, LABELS))], "audio": audio})
        provenance.append({"case_id": case_id, "sample_id": row.sample_id, "diagnostic_rank": rank,
                           "split": "validation", "validation_role": "reliability",
                           "diagnostic_case_sha256": sha(diagnostic / "cases" / (row.sample_id + ".json"))})
        print(f"Verified {case_id}: {row.sample_id}", flush=True)
    # Reuse the existing six-trial headphone setup assets without changing C1/C4.
    screen_dir = ROOT / "survey/deploy/study"
    screen = json.loads((screen_dir / "bundle.json").read_text())
    for item in [*screen["headphones"], screen["calibration"]]:
        path = screen_dir / "audio" / item["path"]
        if sha(path) != item["sha256"]:
            raise ValueError("Headphone setup asset changed")
        shutil.copyfile(path, output / "audio" / path.name)
    payload = {"version": VERSION, "seed": SEED, "cases": cases,
               "headphones": screen["headphones"], "volume": screen["calibration"],
               "q_variant": "g(U,S,R)", "tau_z": .05, "test_evaluated": False,
               "selection": "Fixed diagnostic ranks 0–7 scored; rank 8 practice; no outcome-based filtering",
               "sources": {"protocol": sha(prepared / "protocol.json"),
                           "calibrators": sha(development / "calibration_tau_0.05/calibrators.json"),
                           "probabilities": sha(development / "calibration_tau_0.05/validation_probabilities.parquet"),
                           "builder": sha(Path(__file__)), "design": sha(Path(__file__).with_name("design.py"))},
               "provenance": provenance, "assignments": [assignment(i) for i in range(12)]}
    write_json(output / "bundle.json", payload)
    write_json(output / "manifest.json", {"status": "complete_rehearsal_bundle", "test_evaluated": False,
        "files": {p.relative_to(output).as_posix(): sha(p) for p in output.rglob("*") if p.is_file()}})
    print(f"Bundle saved: {output}. No model fitting or test evaluation performed.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_BUNDLE)
    args = parser.parse_args()
    build(args.output)
