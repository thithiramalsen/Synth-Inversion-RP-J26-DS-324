"""Build the corpus dataset of PREDICTED C1 descriptors joined with synth parameters.

One row per v4 corpus sound: the 13 generating controls (normalized values and
native display units) plus the four descriptor predictions of a trained C1 model,
its weak-support flag and provenance. The descriptor columns are model output,
never human labels: do not train C1 on them or report them as ratings.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.build_predicted_dataset
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.build_predicted_dataset --model-run c1_timbre/models/<real run>

Output (data/processed/c1_predictions/):
    <run>_corpus_dataset.parquet   full table (131,072 rows)
    <run>_corpus_dataset_sample.csv  first 1,000 rows for a quick look
    <run>_corpus_dataset.json      provenance, column guide and summary
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from c1_timbre.features_v2 import FEATURE_VERSION
from c1_timbre.predict_c1 import CORPUS_FEATURES, DEFAULT_RUN, TRAITS, Predictor

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/raw/corpus_v4/manifest.parquet"
PARAMS = ["wave_frame", "bend_amount", "filter_cutoff", "filter_resonance", "filter_drive", "amp_attack", "amp_decay",
          "amp_sustain", "amp_release", "filter_env_amount", "filter_env_attack", "filter_env_decay", "filter_env_sustain"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-run", type=Path, default=DEFAULT_RUN)
    args = ap.parse_args()
    run = args.model_run.resolve()
    out_dir = ROOT / "data/processed/c1_predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"{run.name}_corpus_dataset"

    predictor = Predictor(run)
    feats = pd.read_parquet(CORPUS_FEATURES).set_index("sample_id")
    if (feats.feature_error != "").any():
        raise ValueError("Some corpus sounds have no features; re-run extract_corpus_features")
    pred = predictor.predict_features(feats)

    cols = ["sample_id", "sample_index"] + [f"{p}_normalized" for p in PARAMS] + [f"{p}_display" for p in PARAMS]
    manifest = pd.read_parquet(MANIFEST, columns=cols).set_index("sample_id")
    data = manifest.rename(columns={f"{p}_normalized": p for p in PARAMS})
    for t in TRAITS:
        data[f"pred_{t}"] = pred[t]
        data[f"pred_{t}_raw"] = pred[f"{t}_raw"]
    data["support_distance"] = pred.support_distance
    data["weak_support"] = pred.weak_support
    data["label_type"] = "model_prediction_not_human_label"
    data["label_source"] = pred.label_source
    data["model_run"] = run.name
    data["feature_version"] = FEATURE_VERSION
    data = data.reset_index()
    if len(data) != len(manifest) or data[[f"pred_{t}" for t in TRAITS]].isna().any().any():
        raise RuntimeError("Join lost rows or produced missing predictions")

    data.to_parquet(stem.with_suffix(".parquet"), index=False)
    data.head(1000).to_csv(stem.parent / (stem.name + "_sample.csv"), index=False)

    corr = {t: {p: round(float(np.corrcoef(data[p], data[f"pred_{t}"])[0, 1]), 3) for p in PARAMS} for t in TRAITS}
    meta = dict(
        WARNING="Descriptor columns are MODEL PREDICTIONS, not human ratings."
                + (" The model was trained on SIMULATED ratings, so they follow an artificial rule." if predictor.simulated else ""),
        created_utc=f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}", rows=int(len(data)),
        model_run=run.name, label_source=predictor.label_source, model_file="model_final_all_sounds.json",
        model_sha256=sha(run / "model_final_all_sounds.json"), feature_version=FEATURE_VERSION,
        corpus_manifest=str(MANIFEST.relative_to(ROOT)).replace("\\", "/"), corpus_manifest_sha256=sha(MANIFEST),
        audio_policy="dc_highpass_10hz_v1 applied once to the raw FLOAT master (features are gain-invariant)",
        weak_support=dict(count=int(data.weak_support.sum()), threshold=predictor.threshold,
                          meaning="unlike every training sound; prediction is an extrapolation"),
        columns={
            "sample_id / sample_index": "v4 corpus identity (join key to audio and other components)",
            "<13 parameters>": "generating control values, normalized 0-1 Vital units (genuine labels)",
            "<parameter>_display": "the same control in Vital's native display units",
            "pred_<descriptor>": "predicted listener mean, clipped to the 1-7 scale (display rule)",
            "pred_<descriptor>_raw": "unclipped ridge output",
            "support_distance / weak_support": "distance to nearest training sound and its flag",
            "label_type / label_source / model_run / feature_version": "provenance on every row"},
        summary={t: dict(mean=float(data[f"pred_{t}"].mean()), sd=float(data[f"pred_{t}"].std()),
                         p05=float(data[f"pred_{t}"].quantile(.05)), p95=float(data[f"pred_{t}"].quantile(.95)),
                         clipped=int(((data[f"pred_{t}_raw"] < 1) | (data[f"pred_{t}_raw"] > 7)).sum())) for t in TRAITS},
        parameter_correlations=dict(values=corr, note="descriptive association across the corpus, not the causal effect of a control"))
    stem.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"Wrote {stem.with_suffix('.parquet')} ({len(data):,} rows, {data.shape[1]} columns)")
    for t in TRAITS:
        s = meta["summary"][t]
        top = sorted(corr[t].items(), key=lambda kv: -abs(kv[1]))[:3]
        print(f"  pred_{t:15s} mean {s['mean']:.2f}  5-95% {s['p05']:.2f}-{s['p95']:.2f}  strongest controls: "
              + ", ".join(f"{p} {r:+.2f}" for p, r in top))


if __name__ == "__main__":
    main()
