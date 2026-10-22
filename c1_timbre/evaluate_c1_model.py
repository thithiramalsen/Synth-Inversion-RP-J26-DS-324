"""Validity evaluation for a trained C1 ridge model run (train_c1_model.py output).

Questions answered, per descriptor, all with sound-grouped cross-validation over
every labelled sound and the ridge penalty re-chosen inside each training fold:

1. Stability     repeated 5-fold CV: spread of MAE, R2, Spearman; share of
                 repeats that beat the train-mean baseline
2. Significance  permutation test: the same CV on shuffled targets
3. Ceiling       split-half listener reliability (noise ceiling) and listener
                 generalization: train on one half of each sound's listeners,
                 test against the other half, compared with half-vs-half agreement
4. Construct     feature-group ablation (spectral / temporal / modulation)
5. Data          learning curve over training-set size
6. Robustness    median targets; calibration slope and error by target range

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.evaluate_c1_model
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.evaluate_c1_model --model-run c1_timbre/models/<real run>

Output: <run>/evaluation/ (evaluation.json, REPORT.md, learning_curve.png).
Simulated runs test the software only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from scipy.stats import pearsonr

from c1_timbre.c1_model import fit_with_selection, kfold, safe_spearman
from c1_timbre.features_v2 import FEATURE_NAMES

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
GROUPS = dict(spectral=FEATURE_NAMES[:8], temporal=FEATURE_NAMES[8:17], modulation=FEATURE_NAMES[17:])
EXPECTED_GROUP = dict(brightness="spectral", roughness="modulation", percussiveness="temporal", sustainedness="temporal")
REPEATS, PERMUTATIONS, SPLIT_HALVES, LC_REPEATS, FOLDS = 20, 200, 50, 10, 5
SEED = 20261014


def cv_predict(X, y, rng, folds=FOLDS):
    pred, base = np.empty(len(y)), np.empty(len(y))
    for test in kfold(len(y), folds, rng):
        train = np.setdiff1d(np.arange(len(y)), test)
        model, _ = fit_with_selection(X[train], y[train], rng)
        pred[test], base[test] = model.predict(X[test]), y[train].mean()
    return pred, base


def scores(y, pred, base):
    sst = np.sum((y - base) ** 2)
    return dict(mae=float(np.mean(np.abs(y - pred))), baseline_mae=float(np.mean(np.abs(y - base))),
                r2=float(1 - np.sum((y - pred) ** 2) / sst), spearman=safe_spearman(y, pred),
                pearson=float(pearsonr(y, pred)[0]))


def summarize(values):
    v = np.array([x for x in values if x is not None], float)
    return dict(mean=float(v.mean()), p2_5=float(np.percentile(v, 2.5)), p97_5=float(np.percentile(v, 97.5)))


def listener_halves(ratings: pd.DataFrame, trait: str, sounds, rng):
    """Per sound, split its listeners at random into two halves; return half means."""
    a, b = np.full(len(sounds), np.nan), np.full(len(sounds), np.nan)
    for i, s in enumerate(sounds):
        v = ratings.loc[ratings.sample_id == s, trait].dropna().to_numpy()
        if len(v) < 2:
            continue
        v = rng.permutation(v)
        a[i], b[i] = v[: len(v) // 2].mean(), v[len(v) // 2:].mean()
    return a, b


def learning_curve_png(curves, path: Path, title: str):
    W, H, L, R, T, B = 720, 360, 60, 140, 40, 50
    img = Image.new("RGB", (W, H), "white")
    d, font = ImageDraw.Draw(img), ImageFont.load_default()
    sizes = sorted({n for c in curves.values() for n in c})
    x = lambda n: L + (n - sizes[0]) / (sizes[-1] - sizes[0]) * (W - L - R)
    y = lambda r: T + (1 - max(min(r, 1), 0)) * (H - T - B)
    d.text((L, 12), title, fill="black", font=font)
    for r in np.linspace(0, 1, 6):
        d.line([L, y(r), W - R, y(r)], fill=(225, 225, 225))
        d.text((L - 30, y(r) - 6), f"{r:.1f}", fill="black", font=font)
    for n in sizes:
        d.text((x(n) - 8, H - B + 8), str(n), fill="black", font=font)
    d.text((L + (W - L - R) / 2 - 60, H - 18), "training sounds", fill="black", font=font)
    d.text((6, T - 22), "CV R2", fill="black", font=font)
    colors = [(49, 94, 80), (185, 103, 47), (90, 110, 190), (150, 70, 140)]
    for k, (t, c) in enumerate(curves.items()):
        pts = [(x(n), y(c[n]["r2_mean"])) for n in sizes]
        d.line(pts, fill=colors[k], width=3)
        for px, py in pts:
            d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=colors[k])
        d.text((W - R + 12, T + 16 * k), t, fill=colors[k], font=font)
    img.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-run", type=Path, default=ROOT / "c1_timbre/models/c1_ridge_main_SIMULATED_v1")
    args = ap.parse_args()
    run = args.model_run.resolve()
    out = run / "evaluation"
    out.mkdir(exist_ok=True)
    rng = np.random.default_rng(SEED)
    meta = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    feats = pd.read_csv(run / "features.csv", index_col="sample_id")[FEATURE_NAMES]
    targets = pd.read_csv(run / "targets.csv", index_col="sample_id")
    raw = pd.read_csv(ROOT / meta["responses"], dtype=str, keep_default_na=False)
    ratings = raw[(raw.analysis_include == "True") & (raw.kind == "primary")].copy()
    for t in TRAITS:
        ratings[t] = pd.to_numeric(ratings[t].where(ratings[t] != "unclear"), errors="coerce")
    truth_path = (ROOT / meta["responses"]).parent / "simulation_ground_truth.csv"  # the simulation this run used
    truth = pd.read_csv(truth_path).set_index("sample_id") if meta["simulated"] and truth_path.exists() else None

    result = dict(run=run.name, label_source=meta["label_source"], simulated=meta["simulated"],
                  design=dict(sounds=len(feats), repeats=REPEATS, folds=FOLDS, permutations=PERMUTATIONS,
                              split_halves=SPLIT_HALVES, learning_curve_repeats=LC_REPEATS), descriptors={})
    curves = {}
    for t in TRAITS:
        ok = targets[f"{t}_mean"].notna()
        sounds = targets.index[ok]
        X, y = feats.loc[sounds].to_numpy(), targets.loc[sounds, f"{t}_mean"].to_numpy()
        e = {}

        # 1. stability
        reps = [scores(y, *cv_predict(X, y, rng)) for _ in range(REPEATS)]
        e["repeated_cv"] = {k: summarize([r[k] for r in reps]) for k in ("mae", "baseline_mae", "r2", "spearman")}
        e["repeated_cv"]["share_beating_baseline"] = float(np.mean([r["mae"] < r["baseline_mae"] for r in reps]))
        real_r2 = e["repeated_cv"]["r2"]["mean"]

        # 2. significance
        null = [scores(y, *cv_predict(X, rng.permutation(y), rng))["r2"] for _ in range(PERMUTATIONS)]
        e["permutation"] = dict(null_mean_r2=float(np.mean(null)), null_p95_r2=float(np.percentile(null, 95)),
                                p_value=float((1 + np.sum(np.array(null) >= real_r2)) / (PERMUTATIONS + 1)))

        # 3. ceiling and listener generalization
        human, model_new, ceilings = [], [], []
        for _ in range(SPLIT_HALVES):
            a, b = listener_halves(ratings, t, sounds, rng)
            m = np.isfinite(a) & np.isfinite(b)
            r_ab = pearsonr(a[m], b[m])[0]
            human.append(r_ab)
            ceilings.append(2 * r_ab / (1 + r_ab))
            pred_a, _ = cv_predict(X[m], a[m], rng)          # model learns from half A only
            model_new.append(pearsonr(pred_a, b[m])[0])       # judged by listeners it never saw
        rel = float(np.mean(ceilings))
        cv_r = float(np.mean([r["pearson"] for r in reps]))
        e["listeners"] = dict(
            split_half_r=float(np.mean(human)), reliability_of_full_mean=rel,
            noise_ceiling_r=float(np.sqrt(max(rel, 0))), model_cv_r=cv_r,
            model_share_of_ceiling=float(cv_r / np.sqrt(rel)) if rel > 0 else None,
            new_listeners=dict(model_trained_on_half_A_vs_half_B_r=float(np.mean(model_new)),
                               half_A_vs_half_B_r=float(np.mean(human)),
                               note="model >= human half means it predicts new listeners as well as other listeners do"))

        # 4. construct validity
        base_r2 = real_r2
        groups = {}
        for g, names in GROUPS.items():
            idx = [FEATURE_NAMES.index(n) for n in names]
            rest = [i for i in range(len(FEATURE_NAMES)) if i not in idx]
            only = np.mean([scores(y, *cv_predict(X[:, idx], y, rng))["r2"] for _ in range(5)])
            without = np.mean([scores(y, *cv_predict(X[:, rest], y, rng))["r2"] for _ in range(5)])
            groups[g] = dict(only_this_group_r2=float(only), without_this_group_r2=float(without), drop=float(base_r2 - without))
        strongest = max(groups, key=lambda g: groups[g]["only_this_group_r2"])
        e["feature_groups"] = dict(groups=groups, strongest_group=strongest, expected_group=EXPECTED_GROUP[t],
                                   matches_expectation=strongest == EXPECTED_GROUP[t])

        # 5. learning curve
        sizes = [n for n in (20, 40, 60, 80) if n < 0.8 * len(y)] + [int(0.8 * len(y))]
        curve = {}
        for n in sizes:
            r2s = []
            for _ in range(LC_REPEATS):
                for test in kfold(len(y), FOLDS, rng):
                    train = rng.permutation(np.setdiff1d(np.arange(len(y)), test))[:n]
                    model, _ = fit_with_selection(X[train], y[train], rng)
                    p, b0 = model.predict(X[test]), np.full(len(test), y[train].mean())
                    r2s.append(1 - np.sum((y[test] - p) ** 2) / np.sum((y[test] - b0) ** 2))
            curve[n] = dict(r2_mean=float(np.mean(r2s)), r2_sd=float(np.std(r2s)))
        gain = curve[sizes[-1]]["r2_mean"] - curve[sizes[-2]]["r2_mean"]
        e["learning_curve"] = dict(points=curve, last_step_gain=float(gain), still_improving=bool(gain > 0.02))
        curves[t] = curve

        # 6. robustness and calibration
        ym = targets.loc[sounds, f"{t}_median"].to_numpy()
        e["median_targets"] = scores(ym, *cv_predict(X, ym, rng))
        pred, base = cv_predict(X, y, rng)
        slope = float(np.polyfit(pred, y, 1)[0])
        terc = pd.qcut(y, 3, labels=["low", "middle", "high"])
        e["calibration"] = dict(observed_on_predicted_slope=slope,
                                note="1 = well calibrated; >1 = predictions compressed toward the middle",
                                mean_error_by_target_range={str(k): float(np.mean((pred - y)[terc == k])) for k in ["low", "middle", "high"]})
        if truth is not None:
            e["simulation_recovery"] = dict(cv_pred_vs_hidden_truth_spearman=safe_spearman(truth.loc[sounds, f"{t}_true_mean"].to_numpy(), pred))
        result["descriptors"][t] = e
        print(f"{t}: done", flush=True)

    (out / "evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    learning_curve_png(curves, out / "learning_curve.png", f"{run.name}: learning curve" + (" (SIMULATED labels)" if meta["simulated"] else ""))

    D = result["descriptors"]
    L = [f"# Validity evaluation: {run.name}", ""]
    if meta["simulated"]:
        L += ["> **SIMULATED labels.** These results check the software against an artificial rule. They are not evidence about human timbre perception.", ""]
    L += [f"{len(feats)} sounds, sound-grouped {FOLDS}-fold CV, penalty re-chosen inside every training fold.", "",
          "## 1–2. Stability and significance", "",
          "| Descriptor | CV MAE [95% range] | Baseline MAE | CV R² [95% range] | Spearman | Beats baseline | Permutation p |",
          "|---|---|---|---|---|---|---|"]
    for t, e in D.items():
        c = e["repeated_cv"]
        L.append(f"| {t} | {c['mae']['mean']:.2f} [{c['mae']['p2_5']:.2f}, {c['mae']['p97_5']:.2f}] | {c['baseline_mae']['mean']:.2f} | "
                 f"{c['r2']['mean']:.2f} [{c['r2']['p2_5']:.2f}, {c['r2']['p97_5']:.2f}] | {c['spearman']['mean']:.2f} | "
                 f"{c['share_beating_baseline']:.0%} of {REPEATS} | {e['permutation']['p_value']:.3f} |")
    L += ["", "## 3. Listener ceiling and new listeners", "",
          "| Descriptor | Split-half r | Reliability of mean | Noise ceiling r | Model CV r | Share of ceiling | Model→new listeners r | Listeners→other listeners r |",
          "|---|---|---|---|---|---|---|---|"]
    for t, e in D.items():
        l = e["listeners"]
        L.append(f"| {t} | {l['split_half_r']:.2f} | {l['reliability_of_full_mean']:.2f} | {l['noise_ceiling_r']:.2f} | {l['model_cv_r']:.2f} | "
                 f"{l['model_share_of_ceiling']:.0%} | {l['new_listeners']['model_trained_on_half_A_vs_half_B_r']:.2f} | {l['new_listeners']['half_A_vs_half_B_r']:.2f} |")
    L += ["", "## 4. Construct validity (which measurements carry each descriptor)", "",
          "| Descriptor | Spectral only R² | Temporal only R² | Modulation only R² | Strongest | Expected | Match |", "|---|---|---|---|---|---|---|"]
    for t, e in D.items():
        g = e["feature_groups"]
        L.append(f"| {t} | {g['groups']['spectral']['only_this_group_r2']:.2f} | {g['groups']['temporal']['only_this_group_r2']:.2f} | "
                 f"{g['groups']['modulation']['only_this_group_r2']:.2f} | {g['strongest_group']} | {g['expected_group']} | {'yes' if g['matches_expectation'] else 'no'} |")
    L += ["", "## 5. Learning curve (CV R² by number of training sounds)", ""]
    sizes = list(next(iter(curves.values())))
    L += ["| Descriptor | " + " | ".join(map(str, sizes)) + " | Still improving |", "|---|" + "---|" * len(sizes) + "---|"]
    for t, e in D.items():
        L.append(f"| {t} | " + " | ".join(f"{e['learning_curve']['points'][n]['r2_mean']:.2f}" for n in sizes)
                 + f" | {'yes' if e['learning_curve']['still_improving'] else 'no'} |")
    L += ["", "![learning curve](learning_curve.png)", "", "## 6. Robustness and calibration", "",
          "| Descriptor | Median-target R² | Calibration slope | Mean error low / middle / high |", "|---|---|---|---|"]
    for t, e in D.items():
        m = e["calibration"]["mean_error_by_target_range"]
        L.append(f"| {t} | {e['median_targets']['r2']:.2f} | {e['calibration']['observed_on_predicted_slope']:.2f} | "
                 f"{m['low']:+.2f} / {m['middle']:+.2f} / {m['high']:+.2f} |")
    if truth is not None:
        L += ["", "Simulation recovery (CV predictions vs hidden truth, Spearman): "
              + ", ".join(f"{t} {e['simulation_recovery']['cv_pred_vs_hidden_truth_spearman']:.2f}" for t, e in D.items())]
    L += ["", "## How to read this", "",
          "- **Valid baseline:** beats the baseline in nearly all repeats, permutation p < 0.05, and the strongest feature group matches the descriptor's meaning.",
          "- **Ceiling:** model correlation cannot exceed the noise ceiling set by listener agreement. A high share of the ceiling means more listeners, not a bigger model, is the route to improvement.",
          "- **New listeners:** if 'Model→new listeners' is close to 'Listeners→other listeners', the model predicts unseen people about as well as other people do.",
          "- **Learning curve:** if R² is still rising at the largest size, more rated sounds would help.",
          "- **Calibration:** a slope above 1 and positive error at low / negative at high targets means predictions are pulled toward the middle of the scale."]
    (out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
