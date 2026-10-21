"""Train and evaluate the C1 baseline predictor from a survey export.

    export -> per-sound targets -> c1_features_v2 of the heard audio -> held-out
    sound split -> ridge per descriptor (penalty chosen inside training sounds)
    -> test metrics vs train-mean baseline -> negative controls -> saved model

Works the same on simulated and real exports; the label source is carried into
every output. Simulated runs are engineering checks, not C1 results.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.train_c1_model
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.train_c1_model --responses <real export.csv> --bundle <bundle.json> --run-name c1_ridge_main_v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

from c1_timbre.c1_model import (RidgeModel, clip_scores, fit_with_selection, kfold, metrics, safe_spearman,
                                save_models)
from c1_timbre.features_v2 import FEATURE_NAMES, FEATURE_VERSION, extract

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
SIM = ROOT / "c1_timbre/simulated/c1_main_sim_v1"
TEST_FRACTION = 0.2
CV_FOLDS = 5
SHUFFLES = 50
BOOTSTRAPS = 2000
SEED = 20261014


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


# ------------------------------------------------------------------ data
def load_targets(responses: Path):
    raw = pd.read_csv(responses, dtype=str, keep_default_na=False)
    inc = raw[(raw.analysis_include == "True") & (raw.kind == "primary")].copy()
    if inc.empty:
        raise ValueError("No included primary ratings in the export")
    if len(set(zip(inc.bundle_hash, inc.protocol_hash))) != 1:
        raise ValueError("Mixed bundle/protocol versions: train on one version at a time")
    if inc.duplicated(["participant_id", "sample_id"]).any():
        raise ValueError("A listener has two primary ratings of one sound")
    label_source = sorted(set(raw.get("label_source", pd.Series(["human_export"])).replace("", "human_export")))
    rows = []
    for sid, g in inc.groupby("sample_id"):
        row = dict(sample_id=sid, source_sample_id=g.source_sample_id.iloc[0] if "source_sample_id" in g else "",
                   listeners=len(g))
        for t in TRAITS:
            v = pd.to_numeric(g[t].where(g[t] != "unclear"), errors="coerce").dropna()  # unclear = missing
            row.update({f"{t}_mean": v.mean() if len(v) else np.nan, f"{t}_median": v.median() if len(v) else np.nan,
                        f"{t}_sd": v.std(ddof=1) if len(v) > 1 else np.nan, f"{t}_n": len(v)})
        rows.append(row)
    return pd.DataFrame(rows).set_index("sample_id"), label_source, inc.bundle_hash.iloc[0]


def load_features(bundle_path: Path, sounds):
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    rows = {}
    for sid in sounds:
        s = bundle["samples"][sid]
        path = bundle_path.parent / s["feature_path"]  # FLOAT copy of exactly the heard signal
        if sha(path) != s["feature_sha256"]:
            raise ValueError(f"Feature audio hash mismatch: {sid}")
        audio, sr = sf.read(path, dtype="float64")
        rows[sid] = extract(audio, sr)
    feats = pd.DataFrame.from_dict(rows, orient="index")[FEATURE_NAMES]
    return feats, bundle


def split_sounds(targets: pd.DataFrame, rng):
    """Held-out sounds, stratified by brightness+percussiveness so the test set spans the range."""
    key = targets[[f"{t}_mean" for t in TRAITS]].rank(pct=True).mean(axis=1)
    order = key.sort_values().index.to_numpy()
    n_test = max(2, round(TEST_FRACTION * len(order)))
    strata = np.array_split(order, n_test)
    test = [rng.choice(s) for s in strata]
    return np.array(sorted(set(order) - set(test))), np.array(sorted(test))


# ------------------------------------------------------------------ evaluation helpers
def bootstrap(y, pred, base, rng):
    n = len(y)
    maes, gains, rhos = [], [], []
    for _ in range(BOOTSTRAPS):
        i = rng.integers(0, n, n)
        maes.append(np.mean(np.abs(y[i] - pred[i])))
        gains.append(np.mean(np.abs(y[i] - base[i])) - maes[-1])
        r = safe_spearman(y[i], pred[i])
        if r is not None:
            rhos.append(r)
    ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else None
    return dict(mae_95ci=ci(maes), mae_gain_over_baseline_95ci=ci(gains), spearman_95ci=ci(rhos))


def outer_cv(X, y, rng):
    """Nested CV on training sounds only: penalty re-selected inside every fold."""
    pred, base = np.empty(len(y)), np.empty(len(y))
    for test in kfold(len(y), CV_FOLDS, rng):
        train = np.setdiff1d(np.arange(len(y)), test)
        model, _ = fit_with_selection(X[train], y[train], rng)
        pred[test], base[test] = model.predict(X[test]), y[train].mean()
    return metrics(y, pred, base)


def negative_controls(Xtr, ytr, Xte, yte, rng):
    base = np.full(len(yte), ytr.mean())
    shuffled = []
    for _ in range(SHUFFLES):
        m, _ = fit_with_selection(Xtr, rng.permutation(ytr), rng)
        shuffled.append(metrics(yte, m.predict(Xte), base)["r2_vs_train_mean"])
    noise_tr, noise_te = rng.normal(size=Xtr.shape), rng.normal(size=Xte.shape)
    m_noise, _ = fit_with_selection(noise_tr, ytr, rng)
    const = np.full_like(ytr, ytr.mean())
    m_const = RidgeModel().fit(Xtr, const, 1.0)
    return dict(
        shuffled_targets=dict(runs=SHUFFLES, mean_test_r2=float(np.mean(shuffled)), p95_test_r2=float(np.percentile(shuffled, 95))),
        noise_only_features=metrics(yte, m_noise.predict(Xte), base),
        constant_target=dict(test_prediction_sd=float(np.std(m_const.predict(Xte))),
                             spearman=safe_spearman(yte, m_const.predict(Xte)), note="spearman undefined for constant predictions"))


def ablation(Xtr, ytr, Xte, yte, model, rng):
    """Remove the 3 most heavily weighted features and refit."""
    top = np.argsort(-np.abs(model.coef))[:3]
    keep = np.setdiff1d(np.arange(Xtr.shape[1]), top)
    m, _ = fit_with_selection(Xtr[:, keep], ytr, rng)
    out = metrics(yte, m.predict(Xte[:, keep]), np.full(len(yte), ytr.mean()))
    out["removed"] = [FEATURE_NAMES[i] for i in top]
    return out


def scatter_grid(panels, path: Path, title: str):
    w, h, pad = 300, 300, 40
    img = Image.new("RGB", (w * len(panels), h + 40), "white")
    dr, font = ImageDraw.Draw(img), ImageFont.load_default()
    dr.text((10, 8), title, fill="black", font=font)
    for k, (name, y, p) in enumerate(panels):
        x0, y0 = k * w, 40
        X = lambda v: x0 + pad + (v - 1) / 6 * (w - 2 * pad)
        Y = lambda v: y0 + h - pad - (v - 1) / 6 * (h - 2 * pad)
        dr.rectangle([X(1), Y(7), X(7), Y(1)], outline=(190, 190, 190))
        dr.line([X(1), Y(1), X(7), Y(7)], fill=(200, 200, 200))
        for a, b in zip(y, np.clip(p, 1, 7)):
            dr.ellipse([X(a) - 3, Y(b) - 3, X(a) + 3, Y(b) + 3], fill=(49, 94, 80))
        dr.text((x0 + pad, y0 + 4), f"{name}: observed (x) vs predicted (y), 1-7", fill="black", font=font)
    img.save(path)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--responses", type=Path, default=SIM / "c1_main_responses_SIMULATED.csv")
    ap.add_argument("--bundle", type=Path, default=ROOT / "data/processed/c1_main_v1_simpilot_dryrun/bundle.json")
    ap.add_argument("--ground-truth", type=Path, default=SIM / "simulation_ground_truth.csv",
                    help="simulated runs only: hidden truth for a recovery check (never a model input)")
    ap.add_argument("--run-name", default="c1_ridge_main_SIMULATED_v1")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    out = ROOT / "c1_timbre/models" / args.run_name
    if out.exists():
        if not args.overwrite:
            raise FileExistsError(f"{out} exists; use --overwrite or a new --run-name")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rng = np.random.default_rng(args.seed)

    targets, label_source, bundle_hash = load_targets(args.responses.resolve())
    if bundle_hash != sha(args.bundle):
        raise ValueError("The export was collected with a different bundle than --bundle")
    feats, bundle = load_features(args.bundle.resolve(), targets.index)
    simulated = any(s != "human_export" for s in label_source)
    train_ids, test_ids = split_sounds(targets, rng)
    split = pd.DataFrame(dict(sample_id=list(train_ids) + list(test_ids),
                              split=["train"] * len(train_ids) + ["test"] * len(test_ids)))
    split["source_sample_id"] = split.sample_id.map(targets.source_sample_id)
    split.to_csv(out / "split.csv", index=False)
    targets.to_csv(out / "targets.csv")
    feats.to_csv(out / "features.csv", index_label="sample_id")

    truth = None
    if simulated and args.ground_truth and args.ground_truth.exists():
        truth = pd.read_csv(args.ground_truth).set_index("sample_id")

    report = dict(run=args.run_name, label_source=label_source, simulated=simulated,
                  warning="SIMULATED labels: engineering check of the software, not perceptual evidence" if simulated else None,
                  created_utc=f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}", seed=args.seed,
                  responses=rel(args.responses), responses_sha256=sha(args.responses), bundle=rel(args.bundle),
                  bundle_sha256=bundle_hash, feature_version=FEATURE_VERSION, feature_audio="FLOAT copy of the heard signal",
                  audio_policies=next(iter(bundle["samples"].values()))["policy_ids"],
                  sounds=dict(total=len(targets), train=len(train_ids), test=len(test_ids)), descriptors={})
    evaluated, final, preds = {}, {}, []
    for t in TRAITS:
        y_all = targets[f"{t}_mean"]
        tr = [s for s in train_ids if np.isfinite(y_all[s])]
        te = [s for s in test_ids if np.isfinite(y_all[s])]
        Xtr, Xte = feats.loc[tr].to_numpy(), feats.loc[te].to_numpy()
        ytr, yte = y_all[tr].to_numpy(), y_all[te].to_numpy()
        model, curve = fit_with_selection(Xtr, ytr, rng)
        evaluated[t] = model
        p, base = model.predict(Xte), np.full(len(yte), ytr.mean())
        test = metrics(yte, p, base)
        test_clipped = metrics(yte, clip_scores(p), base)
        se = (targets.loc[te, f"{t}_sd"] / np.sqrt(targets.loc[te, f"{t}_n"])).median()
        terciles = pd.qcut(yte, 3, labels=["low", "middle", "high"])
        by_region = {str(k): dict(n=int((terciles == k).sum()), mae=float(np.mean(np.abs(yte - p)[terciles == k])),
                                  mean_error=float(np.mean((p - yte)[terciles == k]))) for k in ["low", "middle", "high"]}
        entry = dict(alpha=model.alpha, alpha_cv_curve=curve, nested_cv_on_train=outer_cv(Xtr, ytr, rng),
                     test=test, test_clipped_display_rule=test_clipped, test_uncertainty=bootstrap(yte, p, base, rng),
                     test_error_by_target_tercile=by_region,
                     human_disagreement=dict(median_within_sound_sd=float(targets.loc[te, f"{t}_sd"].median()),
                                             median_standard_error_of_target=float(se),
                                             note="error in the target itself from finite listeners; model MAE cannot be judged below this"),
                     weights=dict(sorted(zip(FEATURE_NAMES, map(float, model.coef)), key=lambda kv: -abs(kv[1]))),
                     negative_controls=negative_controls(Xtr, ytr, Xte, yte, rng),
                     ablation_top3=ablation(Xtr, ytr, Xte, yte, model, rng))
        if truth is not None:
            tm = truth.loc[te, f"{t}_true_mean"].to_numpy()
            entry["simulation_recovery"] = dict(spearman_pred_vs_hidden_truth=safe_spearman(tm, p),
                                                mae_pred_vs_hidden_truth=float(np.mean(np.abs(tm - p))),
                                                mae_observed_mean_vs_hidden_truth=float(np.mean(np.abs(tm - yte))))
        report["descriptors"][t] = entry
        all_ok = [s for s in targets.index if np.isfinite(y_all[s])]
        final[t], _ = fit_with_selection(feats.loc[all_ok].to_numpy(), y_all[all_ok].to_numpy(), rng)
        preds += [dict(sample_id=s, descriptor=t, observed_mean=y, predicted=float(q), predicted_display=float(np.clip(q, 1, 7)),
                       split="test") for s, y, q in zip(te, yte, p)]

    provenance = {k: report[k] for k in ("label_source", "responses_sha256", "bundle_sha256", "feature_version", "audio_policies", "seed")}
    save_models(out / "model_evaluated.json", evaluated, FEATURE_NAMES, dict(provenance, trained_on="train split only; the test metrics belong to this model"))
    save_models(out / "model_final_all_sounds.json", final, FEATURE_NAMES, dict(provenance, trained_on="all labelled sounds; for corpus inference; no separate test estimate"))
    pd.DataFrame(preds).to_csv(out / "test_predictions.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    pt = pd.DataFrame(preds)
    scatter_grid([(t, pt[pt.descriptor == t].observed_mean.to_numpy(), pt[pt.descriptor == t].predicted.to_numpy()) for t in TRAITS],
                 out / "test_observed_vs_predicted.png", f"{args.run_name} - held-out sounds" + (" - SIMULATED LABELS" if simulated else ""))

    lines = [f"# {args.run_name}", ""]
    if simulated:
        lines += ["> **SIMULATED labels.** These numbers test the software against an artificial rule. They are not C1 results.", ""]
    lines += [f"Ridge per descriptor on {len(FEATURE_NAMES)} `{FEATURE_VERSION}` features. {len(train_ids)} training sounds, "
              f"{len(test_ids)} held-out sounds. The penalty is chosen by {CV_FOLDS}-fold CV inside the training sounds.", "",
              "| Descriptor | Test MAE [95% CI] | Baseline MAE | R² | Spearman | Outside 1–7 | Shuffled-target R² (p95) | Target SE |",
              "|---|---|---|---|---|---|---|---|"]
    for t, e in report["descriptors"].items():
        ci = e["test_uncertainty"]["mae_95ci"]
        lines.append(f"| {t} | {e['test']['mae']:.2f} [{ci[0]:.2f}, {ci[1]:.2f}] | {e['test']['baseline_mae']:.2f} | "
                     f"{e['test']['r2_vs_train_mean']:.2f} | {e['test']['spearman']:.2f} | {e['test']['outside_1_7']} | "
                     f"{e['negative_controls']['shuffled_targets']['p95_test_r2']:.2f} | "
                     f"{e['human_disagreement']['median_standard_error_of_target']:.2f} |")
    lines += ["", "Top weights (standardized features):", ""]
    for t, e in report["descriptors"].items():
        lines.append(f"- **{t}**: " + ", ".join(f"{k} {v:+.2f}" for k, v in list(e["weights"].items())[:4]))
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
