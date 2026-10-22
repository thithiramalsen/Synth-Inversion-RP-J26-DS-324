"""CLAP + ridge comparison model for C1, evaluated against the 19-feature ridge.

    audio heard by listeners -> CLAP audio embedding (512) -> ridge per descriptor

CLAP is the checkpoint the team uses for C4 (laion/clap-htsat-unfused, pinned
revision), fed the level-matched FLOAT copy of exactly the signal participants
heard, resampled 44.1 -> 48 kHz and L2-normalized. Three inputs are compared on
the SAME targets, held-out split and cross-validation folds:

    features19   the 19 c1_features_v2 features (the main C1 model)
    clap512      the CLAP embedding alone
    combined     19 features + 16 CLAP principal components (PCA fitted inside
                 each training fold only)

Ridge penalties are chosen by inner 5-fold CV over training sounds only, from one
shared alpha grid. The base run supplies targets, split and provenance; it is
read, never modified.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.train_c1_clap
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.train_c1_clap --base-run c1_timbre/models/<real run>

Output: c1_timbre/models/<base run name with "ridge" -> "clap_ridge">/
Embedding cache: data/processed/c1_clap/
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
from scipy.signal import resample_poly
from scipy.stats import pearsonr

from c1_timbre.c1_model import RidgeModel, kfold, metrics, safe_spearman, save_models
from c1_timbre.features_v2 import FEATURE_NAMES

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
MODEL_ID = "laion/clap-htsat-unfused"
MODEL_REVISION = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"   # same pin as c4_metric
ALPHAS = np.logspace(-3, 5, 33)
PCA_COMPONENTS = 16
REPEATS, FOLDS, PERMUTATIONS = 20, 5, 200
SEED = 20261014
VARIANTS = ("features19", "clap512", "combined")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------ embeddings
def clap_embeddings(bundle_path: Path, sounds, cache_dir: Path) -> np.ndarray:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    key = hashlib.sha256(json.dumps([MODEL_ID, MODEL_REVISION, sha(bundle_path), list(sounds)]).encode()).hexdigest()[:16]
    cache = cache_dir / f"{bundle_path.parent.name}_{key}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        if list(z["sample_ids"]) == list(sounds):
            print(f"CLAP embeddings from cache {cache.relative_to(ROOT)}")
            return z["embeddings"]
    import torch
    from transformers import ClapAudioModelWithProjection, ClapProcessor
    processor = ClapProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    model = ClapAudioModelWithProjection.from_pretrained(MODEL_ID, revision=MODEL_REVISION).eval()
    audios = []
    for sid in sounds:
        s = bundle["samples"][sid]
        path = bundle_path.parent / s["feature_path"]          # FLOAT copy of the heard, level-matched signal
        if sha(path) != s["feature_sha256"]:
            raise ValueError(f"Audio hash mismatch: {sid}")
        audio, sr = sf.read(path, dtype="float32")
        if sr != 44100 or audio.ndim != 1:
            raise ValueError(f"Unexpected audio format: {sid}")
        audios.append(resample_poly(audio, 160, 147).astype(np.float32))   # CLAP expects 48 kHz
    out = []
    for i in range(0, len(audios), 16):
        inputs = processor(audios=audios[i:i + 16], sampling_rate=48000, return_tensors="pt", padding=True)
        with torch.inference_mode():
            out.append(model(**inputs).audio_embeds.numpy())
        print(f"  CLAP embedded {min(i + 16, len(audios))}/{len(audios)}", flush=True)
    emb = np.concatenate(out).astype(np.float64)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    if not np.isfinite(emb).all():
        raise ValueError("CLAP returned invalid embeddings")
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(cache, embeddings=emb, sample_ids=np.array(list(sounds)))
    (cache.with_suffix(".json")).write_text(json.dumps(dict(
        model=MODEL_ID, revision=MODEL_REVISION, bundle=str(bundle_path.relative_to(ROOT)).replace("\\", "/"),
        bundle_sha256=sha(bundle_path), input="FLOAT feature copy (heard signal), resampled 44.1->48 kHz, L2-normalized",
        sounds=len(sounds), dimension=int(emb.shape[1])), indent=2), encoding="utf-8")
    return emb


# ------------------------------------------------------------------ inputs per fold (no leakage)
def design(variant, F, E, train, test):
    """Return (X_train, X_test, names) for one fold; any PCA is fitted on training rows only."""
    if variant == "features19":
        return F[train], F[test], list(FEATURE_NAMES)
    if variant == "clap512":
        return E[train], E[test], [f"clap_{i:03d}" for i in range(E.shape[1])]
    mu = E[train].mean(0)
    _, _, vt = np.linalg.svd(E[train] - mu, full_matrices=False)
    P = vt[:PCA_COMPONENTS].T
    pcs = lambda rows: (E[rows] - mu) @ P
    names = list(FEATURE_NAMES) + [f"clap_pc{i + 1:02d}" for i in range(PCA_COMPONENTS)]
    return np.hstack([F[train], pcs(train)]), np.hstack([F[test], pcs(test)]), names


# ------------------------------------------------------------------ fast exact ridge over the alpha grid
def ridge_path(X, y, alphas=ALPHAS):
    """Same estimator as RidgeModel (train standardization, intercept = mean) for every alpha, via one SVD."""
    mean, sd = X.mean(0), X.std(0)
    sd[sd < 1e-12] = 1.0
    Z = (X - mean) / sd
    u, s, vt = np.linalg.svd(Z, full_matrices=False)
    uty = u.T @ (y - y.mean())
    coefs = [vt.T @ (s / (s ** 2 + a) * uty) for a in alphas]
    return mean, sd, float(y.mean()), coefs


def select_and_fit(X, y, rng):
    errors = np.zeros(len(ALPHAS))
    for test in kfold(len(y), min(FOLDS, len(y)), rng):
        train = np.setdiff1d(np.arange(len(y)), test)
        mean, sd, b, coefs = ridge_path(X[train], y[train])
        Zt = (X[test] - mean) / sd
        errors += [np.sum((y[test] - b - Zt @ c) ** 2) for c in coefs]
    best = int(np.argmin(errors))
    mean, sd, b, coefs = ridge_path(X, y, ALPHAS[best:best + 1])
    m = RidgeModel()
    m.mean, m.sd, m.intercept, m.alpha, m.coef = mean, sd, b, float(ALPHAS[best]), coefs[0]
    return m


def cv_predict(variant, F, E, y, folds, rng):
    pred, base = np.empty(len(y)), np.empty(len(y))
    for test in folds:
        train = np.setdiff1d(np.arange(len(y)), test)
        Xtr, Xte, _ = design(variant, F, E, train, test)
        pred[test] = select_and_fit(Xtr, y[train], rng).predict(Xte)
        base[test] = y[train].mean()
    return pred, base


def cv_scores(y, pred, base):
    return dict(mae=float(np.mean(np.abs(y - pred))), baseline_mae=float(np.mean(np.abs(y - base))),
                r2=float(1 - np.sum((y - pred) ** 2) / np.sum((y - base) ** 2)),
                spearman=safe_spearman(y, pred), pearson=float(pearsonr(y, pred)[0]))


def interval(values):
    v = np.asarray(values, float)
    return dict(mean=float(v.mean()), p2_5=float(np.percentile(v, 2.5)), p97_5=float(np.percentile(v, 97.5)))


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-run", type=Path, default=ROOT / "c1_timbre/models/c1_ridge_main_SIMULATED_v1")
    ap.add_argument("--permutations", type=int, default=PERMUTATIONS)
    args = ap.parse_args()
    base_run = args.base_run.resolve()
    out = base_run.parent / base_run.name.replace("ridge", "clap_ridge", 1)
    if out == base_run:
        out = base_run.parent / (base_run.name + "_clap")
    out.mkdir(parents=True, exist_ok=True)

    meta = json.loads((base_run / "metrics.json").read_text(encoding="utf-8"))
    targets = pd.read_csv(base_run / "targets.csv", index_col="sample_id")
    split = pd.read_csv(base_run / "split.csv", index_col="sample_id").loc[targets.index, "split"]
    feats = pd.read_csv(base_run / "features.csv", index_col="sample_id").loc[targets.index, FEATURE_NAMES]
    ceiling_path = base_run / "evaluation/evaluation.json"
    ceiling = ({t: d["listeners"]["noise_ceiling_r"] for t, d in json.loads(ceiling_path.read_text(encoding="utf-8"))["descriptors"].items()}
               if ceiling_path.exists() else {})
    bundle_path = ROOT / meta["bundle"]
    sounds = list(targets.index)
    E_all = clap_embeddings(bundle_path, sounds, ROOT / "data/processed/c1_clap")
    F_all = feats.to_numpy(float)

    result = dict(run=out.name, base_run=base_run.name, simulated=meta["simulated"], label_source=meta["label_source"],
                  warning=meta.get("warning"), created_utc=f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
                  clap=dict(model=MODEL_ID, revision=MODEL_REVISION, dimension=int(E_all.shape[1]),
                            input="level-matched FLOAT copy of the heard signal, 48 kHz, L2-normalized"),
                  design=dict(sounds=len(sounds), train=int((split == "train").sum()), test=int((split == "test").sum()),
                              repeats=REPEATS, folds=FOLDS, permutations=args.permutations,
                              alphas=[float(ALPHAS[0]), float(ALPHAS[-1]), len(ALPHAS)], pca_components=PCA_COMPONENTS),
                  descriptors={})
    rows, test_rows, final_models, eval_models = [], [], {}, {}
    for t in TRAITS:
        ok = targets[f"{t}_mean"].notna().to_numpy()
        y, F, E = targets[f"{t}_mean"].to_numpy()[ok], F_all[ok], E_all[ok]
        sids, spl = np.array(sounds)[ok], split.to_numpy()[ok]
        tr, te = np.where(spl == "train")[0], np.where(spl == "test")[0]
        d = {}
        rep = {v: [] for v in VARIANTS}
        for r in range(REPEATS):
            folds = kfold(len(y), FOLDS, np.random.default_rng(SEED + r))      # identical folds for every variant
            for v in VARIANTS:
                rep[v].append(cv_scores(y, *cv_predict(v, F, E, y, folds, np.random.default_rng(SEED + 1000 + r))))
        for v in VARIANTS:
            Xtr, Xte, names = design(v, F, E, tr, te)
            model = select_and_fit(Xtr, y[tr], np.random.default_rng(SEED))
            pred = model.predict(Xte)
            test = metrics(y[te], pred, np.full(len(te), y[tr].mean()))
            cv = {k: interval([s[k] for s in rep[v]]) for k in ("mae", "baseline_mae", "r2", "spearman", "pearson")}
            share = cv["pearson"]["mean"] / ceiling[t] if ceiling.get(t) else None
            d[v] = dict(test=test, alpha=model.alpha, inputs=len(names), cv=cv, ceiling_share=share,
                        beats_baseline=float(np.mean([s["mae"] < s["baseline_mae"] for s in rep[v]])))
            rows.append(dict(descriptor=t, model=v, inputs=len(names), test_mae=test["mae"], test_baseline_mae=test["baseline_mae"],
                             test_r2=test["r2_vs_train_mean"], test_spearman=test["spearman"], cv_mae=cv["mae"]["mean"],
                             cv_r2=cv["r2"]["mean"], cv_r2_low=cv["r2"]["p2_5"], cv_r2_high=cv["r2"]["p97_5"],
                             ceiling_share=share, alpha=model.alpha))
            test_rows += [dict(sample_id=s, descriptor=t, model=v, observed_mean=o, predicted=p)
                          for s, o, p in zip(sids[te], y[te], pred)]
            if v == "clap512":
                eval_models[t] = model
        # paired comparison on identical folds: positive = CLAP better than the 19 features
        for v in ("clap512", "combined"):
            diff = [a["mae"] - b["mae"] for a, b in zip(rep["features19"], rep[v])]
            d[f"{v}_vs_features19"] = dict(mae_improvement=interval(diff), share_of_repeats_better=float(np.mean(np.array(diff) > 0)),
                                           r2_gain=interval([b["r2"] - a["r2"] for a, b in zip(rep["features19"], rep[v])]))
        # significance of CLAP alone: same CV on shuffled targets
        rng = np.random.default_rng(SEED + 7)
        null = [cv_scores(y, *cv_predict("clap512", F, E, perm, kfold(len(y), FOLDS, rng), rng))["r2"]
                for perm in (rng.permutation(y) for _ in range(args.permutations))]
        d["clap512"]["permutation"] = dict(null_p95_r2=float(np.percentile(null, 95)),
                                           p_value=float((1 + np.sum(np.array(null) >= d["clap512"]["cv"]["r2"]["mean"])) / (len(null) + 1)))
        final_models[t] = select_and_fit(E, y, np.random.default_rng(SEED))
        result["descriptors"][t] = d
        print(f"{t:15s} CV R2  features19 {d['features19']['cv']['r2']['mean']:.2f} | clap512 {d['clap512']['cv']['r2']['mean']:.2f}"
              f" | combined {d['combined']['cv']['r2']['mean']:.2f}", flush=True)

    clap_names = [f"clap_{i:03d}" for i in range(E_all.shape[1])]
    prov = dict(base_run=base_run.name, label_source=meta["label_source"], clap_model=MODEL_ID, clap_revision=MODEL_REVISION)
    save_models(out / "model_evaluated.json", eval_models, clap_names, dict(prov, trained_on="train split"))
    save_models(out / "model_final_all_sounds.json", final_models, clap_names, dict(prov, trained_on="all sounds"))
    pd.DataFrame(rows).to_csv(out / "comparison.csv", index=False)
    pd.DataFrame(test_rows).to_csv(out / "test_predictions.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_report(out, result)
    print(f"\nWrote {out.relative_to(ROOT)}")


def write_report(out: Path, r: dict):
    L = [f"# CLAP + ridge vs 19-feature ridge ({r['run']})", ""]
    if r["simulated"]:
        L += [f"> **{r['warning']}** The comparison tests the software, not which representation predicts real listeners.", ""]
    L += [f"CLAP `{r['clap']['model']}` @ `{r['clap']['revision'][:10]}` (same pin as C4), {r['clap']['dimension']}-d embedding of "
          f"the {r['clap']['input']}. Same targets, held-out split ({r['design']['train']} train / {r['design']['test']} test) and "
          f"{r['design']['repeats']}×{r['design']['folds']}-fold CV folds for every model; ridge α chosen inside training folds.", "",
          "| Descriptor | Model | Inputs | Test MAE | Baseline | Test R² | CV R² (95% range) | Ceiling share |",
          "|---|---|---|---|---|---|---|---|"]
    for t, d in r["descriptors"].items():
        for v in VARIANTS:
            m = d[v]
            share = f"{m['ceiling_share']:.0%}" if m["ceiling_share"] is not None else "–"
            L.append(f"| {t} | {v} | {m['inputs']} | {m['test']['mae']:.2f} | {m['test']['baseline_mae']:.2f} | "
                     f"{m['test']['r2_vs_train_mean']:.2f} | {m['cv']['r2']['mean']:.2f} ({m['cv']['r2']['p2_5']:.2f}–{m['cv']['r2']['p97_5']:.2f}) | {share} |")
    L += ["", "## Paired comparison on identical folds", "",
          "Positive MAE improvement = the alternative has lower error than the 19-feature ridge.", "",
          "| Descriptor | Alternative | MAE improvement (95% range) | Repeats better | R² gain | CLAP permutation p |",
          "|---|---|---|---|---|---|"]
    for t, d in r["descriptors"].items():
        for v in ("clap512", "combined"):
            c = d[f"{v}_vs_features19"]
            p = f"{d['clap512']['permutation']['p_value']:.3f}" if v == "clap512" else ""
            L.append(f"| {t} | {v} | {c['mae_improvement']['mean']:+.3f} ({c['mae_improvement']['p2_5']:+.3f} to "
                     f"{c['mae_improvement']['p97_5']:+.3f}) | {c['share_of_repeats_better']:.0%} | {c['r2_gain']['mean']:+.3f} | {p} |")
    L += ["", "## Reading this", "",
          "- Prefer CLAP only if it beats the 19 features in most repeats and its improvement range excludes 0; otherwise keep the",
          "  interpretable 19-feature ridge as the main model.",
          "- CLAP dimensions have no individual meaning: no construct-validity check is possible, and control effects through CLAP",
          "  must be checked for smoothness before use.",
          "- `model_final_all_sounds.json` holds the CLAP ridge trained on all sounds (inputs `clap_000…clap_511`)."]
    (out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
