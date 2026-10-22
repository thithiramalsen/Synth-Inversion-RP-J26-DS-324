"""Derive simulation "true" sound means for a main-study plan from a HUMAN pilot.

    pilot ratings (per-sound means) + 19 features  ->  ridge per descriptor
    main-study sound truth = ridge prediction + sound-level deviation (SD = pilot CV residual)
    anchors (pilot sounds re-used in the main study) = their observed pilot means

The output feeds simulate_pilot_ratings.py --truth-means, so a simulated main study
inherits the human pilot's scale, spread and descriptor relations (for example a
brightness~roughness overlap) instead of an artificial proxy rule. The ratings
simulated from it are still SIMULATED.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.truth_from_pilot ^
        --pilot-responses c1_timbre/pilot_data/team_rehearsal_v1/c1_pilot_responses.csv --include-rehearsal ^
        --pilot-bundle survey/deploy/study/c1_participant_bundle_v1.json --plan-version c1_main_v1_teampilot ^
        --output c1_timbre/pilot_data/team_rehearsal_v1/main_truth_from_team_pilot.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

from c1_timbre.c1_model import fit_with_selection, kfold
from c1_timbre.features_v2 import FEATURE_NAMES, extract

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
SEED = 20261022


def pilot_means(path: Path, include_rehearsal: bool) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    if include_rehearsal:
        inc = raw[(raw.phase == "complete") & (raw.withdrawn_at == "") & (raw.kind == "primary")]
    else:
        inc = raw[(raw.analysis_include == "True") & (raw.kind == "primary")]
    for t in TRAITS:
        inc[t] = pd.to_numeric(inc[t].where(inc[t] != "unclear"), errors="coerce")
    return inc.groupby("sample_id")[list(TRAITS)].mean()


def audio_path(bundle_dir: Path, info: dict) -> Path:
    """FLOAT feature copy when shipped, else the PCM16 playback copy (features are gain/format-stable)."""
    f = bundle_dir / info.get("feature_path", "")
    return f if info.get("feature_path") and f.exists() else bundle_dir / info["playback_path"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pilot-responses", type=Path, required=True)
    ap.add_argument("--include-rehearsal", action="store_true")
    ap.add_argument("--pilot-bundle", type=Path, required=True)
    ap.add_argument("--plan-version", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)

    bundle_path = args.pilot_bundle.resolve()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))["samples"]
    means = pilot_means(args.pilot_responses, args.include_rehearsal)
    feats = {}
    for sid in means.index:
        audio, sr = sf.read(audio_path(bundle_path.parent, bundle[sid]), dtype="float64")
        feats[sid] = extract(audio, sr)
    X = pd.DataFrame.from_dict(feats, orient="index").loc[means.index, FEATURE_NAMES].to_numpy()

    plan = ROOT / "c1_timbre/main_study" / args.plan_version
    sel = pd.read_csv(plan / "selected_sounds.csv")
    main_bundle = json.loads((ROOT / "data/processed" / args.plan_version / "bundle.json").read_text(encoding="utf-8"))
    src_by_pilot = {sid: info["source_sample_id"] for sid, info in bundle.items()}
    observed = {src_by_pilot[sid]: means.loc[sid] for sid in means.index}

    rows = {src: dict(source_sample_id=src) for src in sel.sample_id}
    rows.update({info["source_sample_id"]: dict(source_sample_id=info["source_sample_id"])
                 for info in main_bundle["samples"].values()})
    corpus_X = sel.set_index("sample_id")[FEATURE_NAMES]
    info = {}
    for t in TRAITS:
        y = means[t].to_numpy()
        pred = np.empty(len(y))
        for test in kfold(len(y), 8, rng):
            train = np.setdiff1d(np.arange(len(y)), test)
            model, _ = fit_with_selection(X[train], y[train], rng)
            pred[test] = model.predict(X[test])
        resid_sd = float(np.std(y - pred))
        model, _ = fit_with_selection(X, y, rng)
        info[t] = dict(cv_residual_sd=resid_sd, alpha=model.alpha)
        for src, r in rows.items():
            if src in observed:
                r[f"{t}_true_mean"], r["origin"] = float(observed[src][t]), "observed_pilot_mean"
            else:
                x = corpus_X.loc[[src]].to_numpy() if src in corpus_X.index else None
                if x is None:  # practice sound not rated in this pilot: predict from its own audio
                    pid = next(k for k, v in src_by_pilot.items() if v == src)
                    a, sr = sf.read(audio_path(bundle_path.parent, bundle[pid]), dtype="float64")
                    x = pd.DataFrame([extract(a, sr)])[FEATURE_NAMES].to_numpy()
                r[f"{t}_true_mean"] = float(np.clip(model.predict(x)[0] + rng.normal(0, resid_sd), 1.2, 6.8))
                r.setdefault("origin", "pilot_ridge_prediction_plus_sound_effect")
    out = pd.DataFrame(rows.values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    args.output.with_suffix(".json").write_text(json.dumps(dict(
        pilot_responses=str(args.pilot_responses), include_rehearsal=args.include_rehearsal, plan_version=args.plan_version,
        pilot_sounds=int(len(means)), sounds=int(len(out)), origin_counts=out.origin.value_counts().to_dict(),
        models=info, note="Truth for SIMULATED main-study ratings, derived from human pilot means."), indent=2), encoding="utf-8")
    print(out.origin.value_counts().to_dict())
    print({t: round(v["cv_residual_sd"], 2) for t, v in info.items()})
    print(out[[f"{t}_true_mean" for t in TRAITS]].corr().round(2).to_string())


if __name__ == "__main__":
    main()
