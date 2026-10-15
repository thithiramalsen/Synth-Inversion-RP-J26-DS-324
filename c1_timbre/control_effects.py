"""Local control-effect analysis for C1 (research question 3).

For a base patch theta and control j:

    g(theta)  = predictor(features(dc_filter(render(theta))))
    effect_j  = g(theta with control j moved by step) - g(theta)

Steps are fractions of each control's declared range (unit coordinate), applied
one control at a time, in both directions, on base patches spread over the
corpus. Inactive contexts are probed explicitly: with zero filter-envelope depth
the envelope timing/sustain controls should do nothing; with envelope sustain at
1 the envelope decay should do nothing; with amp sustain at 1 amp decay should do
nothing.

Effects describe the MODEL's predicted change. They become human-relevant only
after retraining on real ratings and validating selected pairs with listeners.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.control_effects
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.control_effects --model-run c1_timbre/models/<real run> --bases 40

Output: c1_timbre/control_effects/<model run>/
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
STEPS = (-0.2, -0.1, -0.05, 0.05, 0.1, 0.2)
NEGLIGIBLE = 0.15          # |effect| below this (score units) counts as negligible
CLEAR = 0.5                # |effect| at or above this counts as a clear predicted change
SEED = 20261014
ENV_TIMING = ("filter_env_attack", "filter_env_decay", "filter_env_sustain")


# ------------------------------------------------------------------ worker
def _render_features(task):
    from c1_timbre.c1_render import render_unit
    from c1_timbre.features_v2 import extract
    key, unit = task
    audio, _, _ = render_unit(unit)
    return key, extract(np.asarray(audio, dtype=np.float64))


def render_all(tasks, workers):
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[k] = "1"
    out, t0 = {}, time.time()
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for i, (key, feats) in enumerate(pool.map(_render_features, tasks, chunksize=8), 1):
            out[key] = feats
            if i % 250 == 0 or i == len(tasks):
                print(f"  rendered {i}/{len(tasks)} ({time.time() - t0:.0f} s)", flush=True)
    return out


# ------------------------------------------------------------------ base patches
def choose_bases(dataset: pd.DataFrame, names, n, rng):
    """Greedy maximin over unit controls + predicted descriptors, among supported sounds."""
    pool = dataset[~dataset.weak_support].sample(min(30000, (~dataset.weak_support).sum()), random_state=SEED)
    units = np.column_stack([(pool[c] - lo) / (hi - lo) for c, (lo, hi) in names.items()])
    preds = pool[[f"pred_{t}" for t in TRAITS]].to_numpy()
    preds = (preds - preds.min(0)) / np.ptp(preds, axis=0)
    V = np.hstack([units / np.sqrt(units.shape[1]), preds / np.sqrt(preds.shape[1])])
    sel = [int(np.argmin(((V - V.mean(0)) ** 2).sum(1)))]
    dist = np.full(len(V), np.inf)
    while len(sel) < n:
        dist = np.minimum(dist, ((V - V[sel[-1]]) ** 2).sum(1))
        dist[sel] = -1
        sel.append(int(np.argmax(dist)))
    return pool.iloc[sel].sample_id.tolist()


# ------------------------------------------------------------------ outputs
def heatmap(table: pd.DataFrame, path: Path, title: str):
    controls = table.index.tolist()
    cw, ch, left, top = 130, 28, 170, 70
    img = Image.new("RGB", (left + cw * len(TRAITS) + 20, top + ch * len(controls) + 40), "white")
    d, font = ImageDraw.Draw(img), ImageFont.load_default()
    d.text((10, 10), title, fill="black", font=font)
    d.text((10, 26), "mean predicted change per +10% of the control's range (score units); green = up, orange = down", fill=(90, 90, 90), font=font)
    vmax = max(0.3, float(np.nanmax(np.abs(table.to_numpy()))))
    for j, t in enumerate(TRAITS):
        d.text((left + j * cw + 8, top - 18), t, fill="black", font=font)
    for i, c in enumerate(controls):
        d.text((10, top + i * ch + 8), c, fill="black", font=font)
        for j, t in enumerate(TRAITS):
            v = table.loc[c, t]
            a = min(1.0, abs(v) / vmax)
            base = (49, 94, 80) if v >= 0 else (185, 103, 47)
            col = tuple(int(255 - a * (255 - b)) for b in base)
            x0, y0 = left + j * cw, top + i * ch
            d.rectangle([x0, y0, x0 + cw - 4, y0 + ch - 4], fill=col)
            d.text((x0 + 8, y0 + 8), f"{v:+.2f}", fill="black" if a < 0.6 else "white", font=font)
    img.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-run", type=Path, default=ROOT / "c1_timbre/models/c1_ridge_main_SIMULATED_v1")
    ap.add_argument("--bases", type=int, default=40)
    ap.add_argument("--context-bases", type=int, default=8, help="bases used for inactive-context probes")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    from c1_timbre.c1_render import controls, corpus_unit
    from c1_timbre.predict_c1 import Predictor
    run = args.model_run.resolve()
    out = ROOT / "c1_timbre/control_effects" / run.name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rng = np.random.default_rng(SEED)
    names = controls()
    predictor = Predictor(run)
    dataset = pd.read_parquet(ROOT / "data/processed/c1_predictions" / f"{run.name}_corpus_dataset.parquet")

    bases = choose_bases(dataset, names, args.bases, rng)
    base_units = {b: corpus_unit(b) for b in bases}

    # tasks: (key) -> unit dict
    tasks, meta = [], {}
    for b in bases:
        u0 = base_units[b]
        tasks.append(((b, "base", "", 0.0), u0))
        for c in names:
            for s in STEPS:
                v = u0[c] + s
                if 0 <= v <= 1:
                    u = dict(u0); u[c] = v
                    tasks.append(((b, "step", c, s), u))
    # inactive-context probes: force a context on a few bases, then move the controls it should silence
    probes = dict(env_depth_zero=dict(set={"filter_env_amount": 0.0}, test=ENV_TIMING),
                  env_sustain_one=dict(set={"filter_env_sustain": 1.0, "filter_env_amount": 1.0}, test=("filter_env_decay",)),
                  amp_sustain_one=dict(set={"amp_sustain": 1.0}, test=("amp_decay",)))
    for b in bases[: args.context_bases]:
        for pname, p in probes.items():
            u0 = dict(base_units[b]); u0.update(p["set"])
            tasks.append(((b, pname, "", 0.0), u0))
            for c in p["test"]:
                for s in (-0.2, 0.2):
                    v = u0[c] + s
                    if 0 <= v <= 1 and c not in p["set"]:
                        u = dict(u0); u[c] = v
                        tasks.append(((b, pname, c, s), u))
    print(f"{len(bases)} base patches, {len(tasks)} renders on {args.workers} workers", flush=True)
    feats = render_all(tasks, args.workers)

    keys = list(feats)
    F = pd.DataFrame([feats[k] for k in keys], index=pd.MultiIndex.from_tuples(keys, names=["base", "kind", "control", "step"]))
    F.reset_index().to_parquet(out / "rendered_features.parquet", index=False)  # audio measurements of every render
    P = predictor.predict_features(F)
    raw = P[[f"{t}_raw" for t in TRAITS]].rename(columns=lambda c: c[:-4])

    # effects
    rows = []
    for (b, kind, c, s), r in raw.iterrows():
        if c == "":
            continue
        ref = raw.loc[(b, "base" if kind == "step" else kind, "", 0.0)]
        rows.append(dict(base=b, context=kind, control=c, step=s,
                         **{f"effect_{t}": float(r[t] - ref[t]) for t in TRAITS},
                         **{f"base_{t}": float(ref[t]) for t in TRAITS},
                         weak_support=bool(P.loc[(b, kind, c, s), "weak_support"])))
    eff = pd.DataFrame(rows)
    eff.to_csv(out / "effects_long.csv", index=False)
    main_eff = eff[eff.context == "step"].copy()

    # per-unit sensitivity, expressed per +10% of range
    for t in TRAITS:
        main_eff[f"per10_{t}"] = main_eff[f"effect_{t}"] / main_eff.step * 0.1
    table = main_eff.groupby("control")[[f"per10_{t}" for t in TRAITS]].mean().rename(columns=lambda c: c[6:]).loc[list(names)]
    spread = main_eff.groupby("control")[[f"per10_{t}" for t in TRAITS]].std().rename(columns=lambda c: c[6:]).loc[list(names)]
    plus10 = main_eff[main_eff.step == 0.1]
    sign = plus10.groupby("control").apply(
        lambda g: pd.Series({t: float(np.mean(np.sign(g[f"effect_{t}"]) == np.sign(g[f"effect_{t}"].mean()))) for t in TRAITS})).loc[list(names)]
    summary = []
    for c in names:
        for t in TRAITS:
            g = main_eff[main_eff.control == c]
            e1, e2 = g[g.step == 0.1].set_index("base")[f"effect_{t}"], g[g.step == 0.2].set_index("base")[f"effect_{t}"]
            up, down = g[g.step == 0.1].set_index("base")[f"effect_{t}"], g[g.step == -0.1].set_index("base")[f"effect_{t}"]
            both, both_ud = e1.index.intersection(e2.index), up.index.intersection(down.index)
            summary.append(dict(control=c, descriptor=t, mean_per_10pct=table.loc[c, t], sd_across_bases=spread.loc[c, t],
                                share_same_sign_at_plus10=sign.loc[c, t],
                                linearity_ratio_20_vs_10=float(np.median(e2[both] / e1[both].where(e1[both].abs() > 1e-6))) if len(both) else None,
                                asymmetry_up_plus_down=float(np.mean(up[both_ud] + down[both_ud])) if len(both_ud) else None,
                                n_bases=int(g.base.nunique())))
    pd.DataFrame(summary).to_csv(out / "effect_summary.csv", index=False)
    table.to_csv(out / "effect_table_per10pct.csv")
    simulated = predictor.simulated
    heatmap(table, out / "effect_heatmap.png", f"{run.name}: control effects" + (" (SIMULATED-label model)" if simulated else ""))

    # inactive-context check
    ctx = []
    for pname, p in probes.items():
        sub = eff[eff.context == pname]
        for c in p["test"]:
            s = sub[sub.control == c]
            if len(s):
                active = main_eff[(main_eff.control == c) & (main_eff.step.abs() == 0.2)]
                ctx.append(dict(context=pname, control=c, n=len(s),
                                max_abs_effect=float(s[[f"effect_{t}" for t in TRAITS]].abs().to_numpy().max()),
                                typical_abs_effect_when_active=float(active[[f"effect_{t}" for t in TRAITS]].abs().to_numpy().mean())))
    ctx = pd.DataFrame(ctx)
    ctx.to_csv(out / "inactive_context_check.csv", index=False)

    # candidate pairs for a later human validation study (step +/-0.2)
    cand = main_eff[main_eff.step.abs() == 0.2].copy()
    picks = []
    for t in TRAITS:
        e = cand[f"effect_{t}"]
        groups = dict(increase=cand[e >= CLEAR].sort_values(f"effect_{t}", ascending=False),
                      decrease=cand[e <= -CLEAR].sort_values(f"effect_{t}"),
                      negligible=cand[e.abs() < NEGLIGIBLE].sample(frac=1, random_state=SEED))
        for label, g in groups.items():
            g = g.drop_duplicates("base").head(4)
            picks += [dict(descriptor=t, predicted=label, base=r.base, control=r.control, step=r.step,
                           predicted_change=round(getattr(r, f"effect_{t}"), 2), weak_support=r.weak_support) for r in g.itertuples()]
    weak = cand[cand.weak_support].head(4)
    picks += [dict(descriptor="any", predicted="weak_support", base=r.base, control=r.control, step=r.step,
                   predicted_change=None, weak_support=True) for r in weak.itertuples()]
    pd.DataFrame(picks).to_csv(out / "validation_pair_candidates.csv", index=False)

    info = dict(model_run=run.name, label_source=predictor.label_source, simulated=simulated,
                warning="Effects of a model trained on SIMULATED ratings: they test the software, not perception." if simulated else None,
                created_utc=f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}", bases=bases, steps=list(STEPS),
                renders=len(tasks), step_unit="fraction of each control's declared range (unit coordinate)",
                effect_definition="raw (unclipped) prediction of changed patch minus base patch",
                thresholds=dict(negligible=NEGLIGIBLE, clear=CLEAR), seed=SEED)
    (out / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

    S = pd.DataFrame(summary)
    L = [f"# Control effects: {run.name}", ""]
    if simulated:
        L += ["> **Model trained on SIMULATED ratings.** These are effects of an artificial rule. They test the software, not perception.", ""]
    L += [f"{len(bases)} base patches spread over the corpus, 13 controls, steps {', '.join(f'{s:+.0%}' for s in STEPS)} of each control's range, "
          f"one control at a time ({len(tasks)} Vital renders, same settings as the corpus).", "",
          "## Mean predicted change per +10% of a control's range (score units, 1–7 scale)", "",
          "| Control | " + " | ".join(TRAITS) + " |", "|---|" + "---|" * len(TRAITS)]
    for c in names:
        cells = []
        for t in TRAITS:
            r = S[(S.control == c) & (S.descriptor == t)].iloc[0]
            cells.append(f"{r.mean_per_10pct:+.2f} (±{r.sd_across_bases:.2f}, {r.share_same_sign_at_plus10:.0%})")
        L.append(f"| {c} | " + " | ".join(cells) + " |")
    L += ["", "Cells: mean (± SD across base patches, share of bases with the same direction at +10%).", "",
          "![heatmap](effect_heatmap.png)", "", "## Inactive-context check", "",
          "| Context | Control | Max |effect| in context | Typical |effect| when active |", "|---|---|---|---|"]
    for r in ctx.itertuples():
        L.append(f"| {r.context} | {r.control} | {r.max_abs_effect:.3f} | {r.typical_abs_effect_when_active:.3f} |")
    L += ["", "## Files", "",
          "- `effects_long.csv`: every base × control × step with the four predicted changes",
          "- `effect_summary.csv`: mean, spread, sign consistency, linearity (+20% vs +10%) and asymmetry (+10% plus −10%)",
          "- `inactive_context_check.csv`: controls that should do nothing in a forced context",
          "- `validation_pair_candidates.csv`: original/changed pairs for a later listening check (predicted increase, decrease, negligible, weak support)",
          "", "Effects are local and conditional on the base patch, the audio processing and the model. A feature weight is not a control effect; these numbers come from actually re-rendering the patch."]
    (out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:len(names) + 12]))
    print(ctx.round(3).to_string(index=False))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
