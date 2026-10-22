"""Plan the C1 main study from a pilot export and the full v4 corpus.

Steps (every rule is a named constant below and is recorded in decisions.json):

1. Analyse the pilot export: unclear rates, listener agreement (ICC), spread of
   per-sound means, descriptor redundancy, timing, fatigue and feedback.
2. Fit an inspectable pilot predictor (ridge per descriptor on c1_features_v2)
   with sound-wise cross-validation and a shuffled-target control.
3. Decide the session design: unique sounds per person, listeners per sound,
   hidden repeats, spare assignment capacity and descriptor status.
4. Select 128 main-study sounds from the eligible corpus: pilot anchors plus new
   sounds chosen by greedy maximin over parameter, acoustic and predicted-
   descriptor blocks, with weak-support emphasis and coverage quotas.
5. Write level-matched audio (the pilot's level target), a bundle in the pilot
   bundle format, balanced assignment blocks, a draft protocol config and a
   generated design report.

Run it with SIMULATED pilot data now to build and test the procedure. When the
real pilot export exists, rerun with --pilot-responses/--pilot-sessions pointing
at the real files and a new --version. Simulated-pilot outputs are a dry run, not
the frozen main-study stimulus set.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.plan_main_study
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont
from scipy.stats import spearmanr

from c1_timbre.features_v2 import FEATURE_NAMES, FEATURE_VERSION, extract

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
PARAMS = ["wave_frame", "bend_amount", "filter_cutoff", "filter_resonance", "filter_drive", "amp_attack",
          "amp_decay", "amp_sustain", "amp_release", "filter_env_amount", "filter_env_attack",
          "filter_env_decay", "filter_env_sustain"]

# ------------------------------------------------------------------ design rules
N_SOUNDS = 128
N_PARTICIPANTS = 30
N_ANCHORS = 16                    # pilot sounds re-rated in the main study (drift/link check, not pooled)
HIDDEN_REPEATS = 2                # within-listener test-retest; the pilot had none
MIN_LISTENERS = 5
MAX_UNIQUE_PER_PERSON = 30
MAX_MEDIAN_SESSION_MIN = 25.0       # volunteer listening-session ceiling; override with --max-session-min
TERMS_UNCLEAR_FEEDBACK_LIMIT = 0.30  # share of "Some terms unclear"/"Difficult" feedback
TOO_LONG_FEEDBACK_LIMIT = 0.30    # above this share, do not lengthen sessions beyond the pilot
SPARE_FACTOR = 1.5                # spare blocks = ceil(observed non-completion * participants * factor), >= 4
MIN_SPARES = 4
UNCLEAR_REVISE = 0.15
ICC_REVISE = 0.15
REDUNDANT_R = 0.85
LOW_SPREAD_IQR = 1.0
TARGET_RELIABILITY = 0.80
RIDGE_ALPHAS = np.logspace(-2, 3, 26)
CV_FOLDS = 8
WEAK_SUPPORT_QUANTILE = 0.95
QUOTA_WEIGHT = 0.5                # maximin score multiplier per deficient constraint a candidate helps
WEAK_SUPPORT_BONUS = 0.0          # extra maximin weight for weak support; maximin + quota already reach them
QUOTAS = dict(descriptor_quintile=18, parameter_quartile=24, env_depth_near_zero=6,
              env_sustain_near_one=6, weak_support=16)
SEED = 20261014


# ------------------------------------------------------------------ helpers
def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")


def icc1(values: pd.DataFrame, col: str):
    """One-way random-effects ICC(1) and ICC(1,k0) for unbalanced groups."""
    x = values[["sample_id", col]].dropna()
    g = x.groupby("sample_id")[col]
    n_i, n, groups = g.size(), len(x), g.ngroups
    if groups < 3:
        return None, None, None
    k0 = (n - (n_i ** 2).sum() / n) / (groups - 1)
    grand = x[col].mean()
    msb = (n_i * (g.mean() - grand) ** 2).sum() / (groups - 1)
    msw = ((x[col] - g.transform("mean")) ** 2).sum() / (n - groups)
    icc = (msb - msw) / (msb + (k0 - 1) * msw)
    return float(icc), float((msb - msw) / msb), float(k0)


def spearman_brown(icc, k):
    return None if icc is None else k * icc / (1 + (k - 1) * icc)


# ------------------------------------------------------------------ ridge
class Ridge:
    """Ridge with training-only standardization and inner LOO alpha selection."""

    def fit(self, X, y, alphas=RIDGE_ALPHAS):
        self.mu, self.sd = X.mean(0), X.std(0)
        self.sd[self.sd < 1e-12] = 1.0
        Z = (X - self.mu) / self.sd
        self.y0 = y.mean()
        yc = y - self.y0
        U, s, Vt = np.linalg.svd(Z, full_matrices=False)
        best = None
        for a in alphas:
            d = s ** 2 / (s ** 2 + a)
            h = (U ** 2) @ d + 1 / len(y)
            pred = U @ (d * (U.T @ yc))
            loo = np.mean(((yc - pred) / np.maximum(1 - h, 1e-6)) ** 2)
            if best is None or loo < best[0]:
                best = (loo, a)
        self.alpha = float(best[1])
        self.coef = Vt.T @ ((s / (s ** 2 + self.alpha)) * (U.T @ yc))
        return self

    def predict(self, X):
        return self.y0 + ((X - self.mu) / self.sd) @ self.coef


def cross_validate(X, y, rng, folds=CV_FOLDS):
    order = rng.permutation(len(y))
    pred = np.empty(len(y))
    base = np.empty(len(y))
    for f in range(folds):
        test = order[f::folds]
        train = np.setdiff1d(order, test)
        pred[test] = Ridge().fit(X[train], y[train]).predict(X[test])
        base[test] = y[train].mean()
    sse, sst = np.sum((y - pred) ** 2), np.sum((y - base) ** 2)
    return dict(mae=float(np.mean(np.abs(y - pred))), baseline_mae=float(np.mean(np.abs(y - base))),
                r2_vs_train_mean=float(1 - sse / sst), spearman=float(spearmanr(y, pred)[0]),
                predictions_outside_1_7=int(np.sum((pred < 1) | (pred > 7))))


# ------------------------------------------------------------------ pilot analysis
def analyse_pilot(responses: Path, sessions: Path | None, bundle: dict, bundle_dir: Path, rng):
    raw = pd.read_csv(responses, dtype=str, keep_default_na=False)
    label_source = sorted(set(raw.get("label_source", pd.Series(["human_export"])).replace("", "human_export")))
    inc = raw[raw.analysis_include == "True"]
    primary = inc[inc.kind == "primary"].copy()
    if primary.duplicated(["participant_id", "sample_id"]).any():
        raise ValueError("A listener rated the same sound twice as primary")
    if len(set(zip(inc.bundle_hash, inc.protocol_hash))) != 1:
        raise ValueError("Mixed bundle/protocol versions in pilot export")
    for t in TRAITS:
        primary[t + "_v"] = pd.to_numeric(primary[t].where(primary[t] != "unclear"), errors="coerce")
    sounds = sorted(primary.sample_id.unique())
    means = primary.groupby("sample_id")[[t + "_v" for t in TRAITS]].mean()
    means.columns = list(TRAITS)
    out = dict(label_source=label_source, responses=rel(responses), responses_sha256=sha(responses),
               completed_participants=int(primary.participant_id.nunique()), sounds=len(sounds),
               evaluations=len(primary), listeners_per_sound=sorted(map(int, primary.sample_id.value_counts().unique())),
               descriptors={})
    for t in TRAITS:
        icc, icck, k0 = icc1(primary, t + "_v")
        sd = primary.groupby("sample_id")[t + "_v"].std()
        q1, q3 = means[t].quantile([.25, .75])
        out["descriptors"][t] = dict(unclear_rate=float((primary[t] == "unclear").mean()), icc1=icc, icc1_mean_of_k=icck,
                                     k0=k0, median_within_sound_sd=float(sd.median()),
                                     sound_mean_range=[float(means[t].min()), float(means[t].max())],
                                     sound_mean_iqr=float(q3 - q1),
                                     rating_histogram={str(v): int((primary[t + "_v"] == v).sum()) for v in range(1, 8)})
    corr = means.corr()
    out["sound_mean_correlations"] = {f"{a}~{b}": float(corr.loc[a, b]) for i, a in enumerate(TRAITS) for b in TRAITS[i + 1:]}

    # timing and fatigue
    for c in ("started_at", "submitted_at"):
        primary[c + "_t"] = pd.to_datetime(primary[c], utc=True)
    primary["trial_s"] = (primary.submitted_at_t - primary.started_at_t).dt.total_seconds()
    complete = raw[(raw.phase == "complete") & (raw.withdrawn_at == "")]
    practice = complete[complete.kind == "practice"]
    practice_s = (pd.to_datetime(practice.submitted_at, utc=True) - pd.to_datetime(practice.started_at, utc=True)).dt.total_seconds()
    primary["position"] = primary.groupby("session_id").trial_order.transform(lambda s: s.astype(int).rank())
    slope = float(np.polyfit(primary.position, primary.trial_s, 1)[0])
    resid = []
    for t in TRAITS:
        r = primary[t + "_v"] - primary.groupby("sample_id")[t + "_v"].transform("mean")
        resid.append(pd.DataFrame(dict(position=primary.position, abs_resid=r.abs())).dropna())
    resid = pd.concat(resid)
    half = primary.position.max() / 2
    timing = dict(median_study_trial_s=float(primary.trial_s.median()), median_practice_trial_s=float(practice_s.median()),
                  trial_seconds_slope_per_position=slope,
                  abs_residual_first_half=float(resid[resid.position <= half].abs_resid.mean()),
                  abs_residual_second_half=float(resid[resid.position > half].abs_resid.mean()))
    if sessions is not None:
        s = pd.read_csv(sessions, dtype=str, keep_default_na=False)
        s["fate"] = np.where(s.withdrawn_at != "", "withdrawn", np.where(s.phase == "complete", "complete", "incomplete"))
        done = s[s.fate == "complete"]
        dur = (pd.to_datetime(done.completed_at, utc=True) - pd.to_datetime(done.started_at, utc=True)).dt.total_seconds() / 60
        first = pd.to_datetime(raw.groupby("session_id").started_at.min(), utc=True)
        start = pd.to_datetime(done.set_index("session_id").started_at, utc=True)
        setup = (first.reindex(start.index) - start).dt.total_seconds() / 60
        fb = [json.loads(f) for f in done.feedback_json if f]
        timing.update(median_session_min=float(dur.median()), p90_session_min=float(dur.quantile(.9)),
                      median_setup_min=float(setup.median()))
        out["sessions"] = dict(started=len(s), completed=int((s.fate == "complete").sum()),
                               withdrawn=int((s.fate == "withdrawn").sum()), incomplete=int((s.fate == "incomplete").sum()),
                               non_completion_rate=float((s.fate != "complete").mean()))
        out["feedback"] = dict(n=len(fb), too_long=float(np.mean([f["length"] == "Too long" for f in fb])) if fb else None,
                               terms_unclear=float(np.mean([f["clarity"] != "Clear" for f in fb])) if fb else None)
    out["timing"] = timing

    # pilot predictor on the audio participants heard
    feats = []
    for sid in sounds:
        audio, sr = sf.read(bundle_dir / bundle["samples"][sid]["playback_path"], dtype="float64")
        feats.append(extract(audio, sr))
    X = pd.DataFrame(feats, index=sounds)[FEATURE_NAMES].to_numpy()
    models, out["model"] = {}, {}
    for t in TRAITS:
        y = means.loc[sounds, t].to_numpy()
        ok = np.isfinite(y)
        cv = cross_validate(X[ok], y[ok], rng)
        shuffled = cross_validate(X[ok], rng.permutation(y[ok]), rng)
        models[t] = Ridge().fit(X[ok], y[ok])
        out["model"][t] = dict(cv=cv, shuffled_target_cv=shuffled, alpha=models[t].alpha,
                               top_weights=dict(sorted(zip(FEATURE_NAMES, map(float, models[t].coef)),
                                                       key=lambda kv: -abs(kv[1]))[:5]))
    return out, means, X, sounds, models


# ------------------------------------------------------------------ decisions
def decide(pilot: dict, max_session_min: float = MAX_MEDIAN_SESSION_MIN):
    d = dict(n_sounds=N_SOUNDS, n_participants=N_PARTICIPANTS, n_anchors=N_ANCHORS, hidden_repeats=HIDDEN_REPEATS)
    status = {}
    for t, s in pilot["descriptors"].items():
        flags = []
        if s["unclear_rate"] > UNCLEAR_REVISE:
            flags.append(f"unclear_rate>{UNCLEAR_REVISE}")
        if s["icc1"] is None or s["icc1"] < ICC_REVISE:
            flags.append(f"icc1<{ICC_REVISE}")
        if s["sound_mean_iqr"] < LOW_SPREAD_IQR:
            flags.append(f"sound_mean_iqr<{LOW_SPREAD_IQR}")
        status[t] = dict(action="revise_wording_before_main" if flags else "retain_unchanged", flags=flags)
    unclear_fb = (pilot.get("feedback") or {}).get("terms_unclear")
    d["wording_review_recommended"] = bool(unclear_fb is not None and unclear_fb > TERMS_UNCLEAR_FEEDBACK_LIMIT)
    redundant = [k for k, r in pilot["sound_mean_correlations"].items() if abs(r) > REDUNDANT_R]
    d["descriptor_status"], d["redundant_pairs"] = status, redundant

    tm = pilot["timing"]
    setup = tm.get("median_setup_min", 4.0)
    def minutes(S):
        study = sum(tm["median_study_trial_s"] + tm["trial_seconds_slope_per_position"] * (p - 10.5)
                    for p in range(1, S + HIDDEN_REPEATS + 1))
        return setup + (3 * tm["median_practice_trial_s"] + study) / 60 + 2.0  # + break and feedback
    too_long = (pilot.get("feedback") or {}).get("too_long") or 0
    cap = 20 if too_long > TOO_LONG_FEEDBACK_LIMIT else MAX_UNIQUE_PER_PERSON
    options = []
    for S in range(20, cap + 1):
        k = (N_PARTICIPANTS * S) // N_SOUNDS
        options.append(dict(unique_per_person=S, min_listeners=k, predicted_median_min=round(minutes(S), 1),
                            feasible=k >= MIN_LISTENERS and minutes(S) <= max_session_min))
    feasible = [o for o in options if o["feasible"]]
    if not feasible:
        need = math.ceil(N_SOUNDS * MIN_LISTENERS / 20)
        raise RuntimeError(f"No feasible session length; with 20 sounds/person {need} participants are needed")
    best_k = max(o["min_listeners"] for o in feasible)
    chosen = min((o for o in feasible if o["min_listeners"] == best_k), key=lambda o: o["unique_per_person"])
    S = chosen["unique_per_person"]
    d.update(session_options=options, unique_per_person=S, min_listeners_per_sound=best_k,
             total_primary_ratings=N_PARTICIPANTS * S, sounds_with_extra_listener=N_PARTICIPANTS * S - N_SOUNDS * best_k,
             predicted_median_session_min=chosen["predicted_median_min"], break_after_rated=math.ceil((S + HIDDEN_REPEATS) / 2),
             presentations_per_person=3 + S + HIDDEN_REPEATS)
    d["expected_reliability_of_sound_means"] = {
        t: dict(icc1=s["icc1"], at_min_listeners=spearman_brown(s["icc1"], best_k),
                listeners_for_target=(math.ceil(TARGET_RELIABILITY * (1 - s["icc1"]) / (s["icc1"] * (1 - TARGET_RELIABILITY)))
                                      if s["icc1"] and s["icc1"] > 0 else None))
        for t, s in pilot["descriptors"].items()}
    rate = pilot.get("sessions", {}).get("non_completion_rate", 0.15)
    d["spare_blocks"] = max(MIN_SPARES, math.ceil(rate * N_PARTICIPANTS * SPARE_FACTOR))
    d["assignment_capacity"] = N_PARTICIPANTS + d["spare_blocks"]
    return d


# ------------------------------------------------------------------ selection
def load_corpus(features_path: Path, recipe: dict, pilot_target_rms: float, peak_ceiling: float, exclude: set):
    c = pd.read_parquet(features_path)
    man = pd.read_parquet(ROOT / "data/raw/corpus_v4/manifest.parquet",
                          columns=["sample_id"] + [p + "_normalized" for p in PARAMS])
    c = c.merge(man, on="sample_id", validate="one_to_one")
    for p in PARAMS:
        lo, hi = recipe["parameters"][p]["min"], recipe["parameters"][p]["max"]
        c["u_" + p] = (c[p + "_normalized"] - lo) / (hi - lo)
    reasons = pd.Series("", index=c.index)
    rules = [("raw_clipping", c.raw_clipped), ("silent", c.raw_silent | c.is_silent), ("clipping", c.is_clipped),
             ("DC_warning", c.has_large_dc_offset), ("nonquiet_tail", c.tail_peak > .001),
             ("feature_error", c.feature_error != ""),
             ("level_incompatible_with_pilot_target", peak_ceiling * c.held_rms / c.peak < pilot_target_rms),
             ("duplicate_audio", c.processed_samples_sha256.duplicated()),
             ("pilot_stimulus", c.sample_id.isin(exclude))]
    for name, mask in rules:
        reasons[(reasons == "") & mask.fillna(True).astype(bool)] = name
    c["exclusion"] = reasons
    return c


def scale_block(values: np.ndarray, ref: np.ndarray):
    lo, hi = np.percentile(ref, [1, 99], axis=0)
    return np.clip((values - lo) / np.maximum(hi - lo, 1e-9), -0.2, 1.2)


def choose_anchors(means: pd.DataFrame, n: int):
    z = ((means - means.mean()) / means.std()).fillna(0).to_numpy()
    sel = [int(np.argmin((z ** 2).sum(1)))]
    dist = np.full(len(z), np.inf)
    while len(sel) < n:
        dist = np.minimum(dist, ((z - z[sel[-1]]) ** 2).sum(1))
        dist[sel] = -1
        sel.append(int(np.argmax(dist)))
    return [means.index[i] for i in sel]


def select(pool: pd.DataFrame, anchor_rows: pd.DataFrame, models, pilot_X, rng, log):
    """Greedy maximin with weak-support emphasis, then quota repair by swaps."""
    allrows = pd.concat([anchor_rows.assign(is_anchor=True), pool.assign(is_anchor=False)], ignore_index=True)
    X = allrows[FEATURE_NAMES].to_numpy()
    for t in TRAITS:
        allrows["pred_" + t] = models[t].predict(X)
    zp = (pilot_X - pilot_X.mean(0)) / np.maximum(pilot_X.std(0), 1e-12)
    zx = (X - pilot_X.mean(0)) / np.maximum(pilot_X.std(0), 1e-12)
    nn_pilot = np.array([np.sort(np.sqrt(((zp - zp[i]) ** 2).mean(1)))[1] for i in range(len(zp))])
    threshold = float(np.quantile(nn_pilot, WEAK_SUPPORT_QUANTILE))
    support = np.empty(len(zx))
    for start in range(0, len(zx), 4096):
        block = zx[start:start + 4096]
        support[start:start + 4096] = np.sqrt(((block[:, None, :] - zp[None]) ** 2).mean(2)).min(1)
    allrows["support_distance"] = support
    allrows["weak_support"] = support > threshold

    ref = ~allrows.is_anchor.to_numpy()
    blocks = [scale_block(allrows[["u_" + p for p in PARAMS]].to_numpy(), allrows.loc[ref, ["u_" + p for p in PARAMS]].to_numpy()),
              scale_block(X, X[ref]),
              scale_block(allrows[["pred_" + t for t in TRAITS]].to_numpy(), allrows.loc[ref, ["pred_" + t for t in TRAITS]].to_numpy())]
    V = np.hstack([b / np.sqrt(b.shape[1]) for b in blocks]).astype(np.float32)
    bonus = np.where(allrows.weak_support, 1 + WEAK_SUPPORT_BONUS, 1.0)

    # constraints
    cons = []
    for t in TRAITS:
        edges = np.quantile(allrows.loc[ref, "pred_" + t], [.2, .4, .6, .8])
        q = np.digitize(allrows["pred_" + t], edges)
        cons += [(f"pred_{t}_quintile_{i + 1}", q == i, QUOTAS["descriptor_quintile"]) for i in range(5)]
    for p in PARAMS:
        q = np.clip((allrows["u_" + p] * 4).astype(int), 0, 3)
        cons += [(f"{p}_quartile_{i + 1}", (q == i).to_numpy(), QUOTAS["parameter_quartile"]) for i in range(4)]
    cons.append(("filter_env_amount_lowest_10pct", (allrows.u_filter_env_amount < .1).to_numpy(), QUOTAS["env_depth_near_zero"]))
    cons.append(("filter_env_sustain_ge_0.9", (allrows.u_filter_env_sustain >= .9).to_numpy(), QUOTAS["env_sustain_near_one"]))
    cons.append(("weak_pilot_support", allrows.weak_support.to_numpy(), QUOTAS["weak_support"]))

    # Quota-aware greedy maximin. A candidate's maximin distance is multiplied by
    # (1 + QUOTA_WEIGHT * number of still-deficient constraints it would help).
    # When the remaining slots can only just cover a constraint's deficit, the
    # choice is restricted to that constraint's members.
    M = np.column_stack([mask for _, mask, _ in cons])
    minimum = np.array([m for _, _, m in cons])
    selected = list(np.flatnonzero(allrows.is_anchor))
    counts = M[selected].sum(0)
    dist = np.full(len(V), np.inf, dtype=np.float32)
    for i in selected:
        dist = np.minimum(dist, ((V - V[i]) ** 2).sum(1))
    taken = np.zeros(len(V), bool)
    taken[selected] = True
    forced = 0
    while len(selected) < N_SOUNDS:
        deficit = np.maximum(minimum - counts, 0)
        slots = N_SOUNDS - len(selected)
        helps = M[:, deficit > 0].sum(1)
        scale = np.median(dist[np.isfinite(dist) & ~taken])
        score = (np.minimum(dist, 4 * scale) / scale) * bonus * (1 + QUOTA_WEIGHT * helps)
        urgent = np.flatnonzero(deficit >= slots)
        if len(urgent):
            score[~M[:, urgent].any(1)] = -1
            forced += 1
        score[taken] = -2
        i = int(np.argmax(score))
        selected.append(i)
        taken[i] = True
        counts += M[i]
        dist = np.minimum(dist, ((V - V[i]) ** 2).sum(1))
    coverage = [dict(constraint=n, minimum=m, selected=int(counts[k]),
                     corpus_share=float(mask[ref].mean()), selected_share=float(counts[k] / N_SOUNDS))
                for k, (n, mask, m) in enumerate(cons)]
    unmet = [c["constraint"] for c in coverage if c["selected"] < c["minimum"]]
    log.append(f"quota-aware greedy: {forced} forced picks; unmet constraints: {unmet or 'none'}")
    chosen = allrows.iloc[selected].copy()
    chosen["selection_order"] = range(1, len(chosen) + 1)
    return chosen, allrows, coverage, threshold


# ------------------------------------------------------------------ assignments
def make_assignments(ids, S, capacity, repeats, seed=SEED):
    """Prefix-balanced blocks: after any number of issued blocks, exposure differs by <= 1."""
    rng = random.Random(seed)
    coverage, pairs, blocks = Counter(), Counter(), []
    rep_count = Counter()
    for b in range(capacity):
        chosen = []
        for _ in range(S):
            rest = [s for s in ids if s not in chosen]
            rng.shuffle(rest)
            pick = min(rest, key=lambda s: (coverage[s], sum(pairs[tuple(sorted((s, t)))] for t in chosen)))
            chosen.append(pick)
            coverage[pick] += 1
        for i, a in enumerate(chosen):
            for c in chosen[i + 1:]:
                pairs[tuple(sorted((a, c)))] += 1
        if max(coverage[s] for s in ids) - min(coverage[s] for s in ids) > 1:
            raise RuntimeError("Prefix coverage unbalanced")
        rng.shuffle(chosen)
        trials = [dict(presentation_id=f"rated_{j + 1:02d}", sample_id=s, kind="primary", repeat_of=None)
                  for j, s in enumerate(chosen)]
        half = S // 2
        sources = sorted(trials[:half - 2], key=lambda t: (rep_count[t["sample_id"]], rng.random()))[:repeats]
        positions = sorted(rng.sample(range(half + 4, S + 1), repeats))
        for n, (src, pos) in enumerate(sorted(zip(sources, positions), key=lambda x: x[1])):
            rep_count[src["sample_id"]] += 1
            trials.insert(pos + n, dict(presentation_id=f"repeat_{n + 1:02d}", sample_id=src["sample_id"],
                                        kind="repeat", repeat_of=src["presentation_id"]))
        for k, t in enumerate(trials):
            if t["kind"] == "repeat":
                gap = k - next(i for i, x in enumerate(trials) if x["presentation_id"] == t["repeat_of"]) - 1
                if gap < 6:
                    raise RuntimeError("Repeat too close to its original")
        blocks.append(dict(assignment_id=f"block_{b + 1:02d}", trials=trials))
    return blocks


def prefix_coverage(blocks, ids, prefixes):
    out = {}
    for n in prefixes:
        c = Counter(t["sample_id"] for b in blocks[:n] for t in b["trials"] if t["kind"] == "primary")
        out[str(n)] = {str(k): v for k, v in sorted(Counter(c[s] for s in ids).items())}
    return out


# ------------------------------------------------------------------ plots (PIL; matplotlib is not installed)
def histogram_grid(panels, path: Path, title: str):
    cols, w, h = 4, 300, 200
    rows = math.ceil(len(panels) / cols)
    img = Image.new("RGB", (cols * w, rows * h + 40), "white")
    dr = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    dr.text((10, 10), title + "   grey = eligible corpus, blue = selected (density)", fill="black", font=font)
    for k, (name, corpus, chosen) in enumerate(panels):
        x0, y0 = (k % cols) * w + 20, (k // cols) * h + 50
        lo, hi = np.nanpercentile(corpus, [0.5, 99.5])
        bins = np.linspace(lo, hi, 21)
        hc = np.histogram(np.clip(corpus, lo, hi), bins, density=True)[0]
        hs = np.histogram(np.clip(chosen, lo, hi), bins, density=True)[0]
        top = max(hc.max(), hs.max(), 1e-12)
        bw = (w - 40) / 20
        for i in range(20):
            for vals, col, off in ((hc, (190, 190, 190), 0), (hs, (60, 110, 200), bw / 2)):
                bh = vals[i] / top * (h - 70)
                dr.rectangle([x0 + i * bw + off, y0 + h - 70 - bh, x0 + i * bw + off + bw / 2 - 1, y0 + h - 70], fill=col)
        dr.text((x0, y0 + h - 65), f"{name}\n{lo:.3g} .. {hi:.3g}", fill="black", font=font)
    img.save(path)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sim = ROOT / "c1_timbre/simulated/c1_pilot_sim_v1"
    ap.add_argument("--pilot-responses", type=Path, default=sim / "c1_pilot_responses_SIMULATED.csv")
    ap.add_argument("--pilot-sessions", type=Path, default=sim / "c1_sessions_SIMULATED.csv")
    ap.add_argument("--pilot-bundle", type=Path, default=ROOT / "survey/deploy/study/bundle.json")
    ap.add_argument("--pilot-config", type=Path, default=ROOT / "survey/config/c1_pilot_20_v1.json")
    ap.add_argument("--corpus-features", type=Path, default=ROOT / "data/processed/c1_features_v2/corpus_features.parquet")
    ap.add_argument("--version", default="c1_main_v1_simpilot_dryrun")
    ap.add_argument("--max-session-min", type=float, default=MAX_MEDIAN_SESSION_MIN)
    ap.add_argument("--skip-audio", action="store_true", help="plan and select without writing stimulus audio")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    out = ROOT / "c1_timbre/main_study" / args.version
    audio_root = ROOT / "data/processed" / args.version
    for d in (out, audio_root):
        if d.exists() and any(d.iterdir()):
            if not args.overwrite:
                raise FileExistsError(f"{d} exists; use --overwrite or a new --version")
            shutil.rmtree(d)
    out.mkdir(parents=True)
    rng = np.random.default_rng(SEED)
    log = []

    bundle = json.loads(args.pilot_bundle.read_text(encoding="utf-8"))
    pilot_cfg = json.loads(args.pilot_config.read_text(encoding="utf-8"))
    recipe = json.loads((ROOT / "data/raw/corpus_v4/recipe.json").read_text(encoding="utf-8"))["synthesis"]

    # 1-2. pilot
    pilot, means, pilot_X, pilot_sounds, models = analyse_pilot(
        args.pilot_responses, args.pilot_sessions if args.pilot_sessions and args.pilot_sessions.exists() else None,
        bundle, args.pilot_bundle.parent, rng)
    simulated = any(s != "human_export" for s in pilot["label_source"])
    (out / "pilot_analysis.json").write_text(json.dumps(pilot, indent=2), encoding="utf-8")

    # 3. decisions
    decisions = decide(pilot, args.max_session_min)
    decisions["pilot_label_source"] = pilot["label_source"]
    decisions["status"] = "DRY RUN from simulated pilot - not a frozen stimulus set" if simulated else "draft from human pilot"

    # 4. selection
    pilot_sources = {s["source_sample_id"] for s in bundle["samples"].values()}
    target_rms, ceiling = bundle["level_policy"]["target_rms"], bundle["level_policy"]["peak_ceiling"]
    corpus = load_corpus(args.corpus_features, recipe, target_rms, ceiling, pilot_sources)
    exclusion_counts = corpus.exclusion.replace("", "eligible").value_counts().to_dict()
    pool = corpus[corpus.exclusion == ""]
    anchor_ids = choose_anchors(means.loc[pilot_sounds], N_ANCHORS)
    anchor_src = {bundle["samples"][a]["source_sample_id"]: a for a in anchor_ids}
    anchor_rows = corpus[corpus.sample_id.isin(anchor_src)].copy()
    anchor_rows["pilot_sound_id"] = anchor_rows.sample_id.map(anchor_src)
    if len(anchor_rows) != N_ANCHORS or (anchor_rows.exclusion.isin(["", "pilot_stimulus"]) == False).any():
        raise RuntimeError("Anchor sounds missing or ineligible in the corpus")
    chosen, allrows, coverage, support_threshold = select(pool, anchor_rows, models, pilot_X, rng, log)
    chosen = chosen.sort_values("selection_order")
    chosen["main_sound_id"] = [f"sound_{i:03d}" for i in range(1, N_SOUNDS + 1)]
    keep = (["main_sound_id", "sample_id", "is_anchor", "pilot_sound_id", "selection_order", "support_distance", "weak_support"]
            + ["pred_" + t for t in TRAITS] + [p + "_normalized" for p in PARAMS] + FEATURE_NAMES + ["held_rms", "peak"])
    chosen[keep].to_csv(out / "selected_sounds.csv", index=False)
    pd.DataFrame(coverage).to_csv(out / "coverage_constraints.csv", index=False)

    eligible = allrows[~allrows.is_anchor]
    def ks(a, b):
        grid = np.sort(np.r_[a, b])
        return float(np.max(np.abs(np.searchsorted(np.sort(a), grid, "right") / len(a)
                                   - np.searchsorted(np.sort(b), grid, "right") / len(b))))
    dist_rows = []
    for col in ["pred_" + t for t in TRAITS] + FEATURE_NAMES + [p + "_normalized" for p in PARAMS]:
        e, s = eligible[col].to_numpy(), chosen[col].to_numpy()
        dist_rows.append(dict(variable=col, corpus_p05=np.percentile(e, 5), corpus_median=np.median(e), corpus_p95=np.percentile(e, 95),
                              selected_min=s.min(), selected_median=np.median(s), selected_max=s.max(),
                              selected_share_outside_corpus_p05_p95=float(np.mean((s < np.percentile(e, 5)) | (s > np.percentile(e, 95)))),
                              ks_distance=ks(e, s)))
    pd.DataFrame(dist_rows).to_csv(out / "distribution_comparison.csv", index=False)
    histogram_grid([("pred_" + t, eligible["pred_" + t].to_numpy(), chosen["pred_" + t].to_numpy()) for t in TRAITS]
                   + [(f, eligible[f].to_numpy(), chosen[f].to_numpy()) for f in
                      ("log2_centroid", "log_am_rough_15_150", "held_drop_db", "log_attack_s")],
                   out / "selected_vs_corpus_descriptors_features.png", f"{args.version}: predicted descriptors and key features")
    histogram_grid([(p, eligible[p + "_normalized"].to_numpy(), chosen[p + "_normalized"].to_numpy()) for p in PARAMS],
                   out / "selected_vs_corpus_parameters.png", f"{args.version}: 13 controls")

    # 5. assignments
    S, cap = decisions["unique_per_person"], decisions["assignment_capacity"]
    ids = list(chosen.main_sound_id)
    practice_src = [bundle["samples"][f"sound_{i:03d}"] for i in (65, 66, 67)]
    blocks = make_assignments(ids, S, cap, HIDDEN_REPEATS)
    for b in blocks:
        b["trials"] = [dict(presentation_id=f"practice_{i + 1:02d}", sample_id=f"sound_{N_SOUNDS + i + 1:03d}",
                            kind="practice", repeat_of=None) for i in range(3)] + b["trials"]
    decisions["prefix_coverage"] = prefix_coverage(blocks, ids, [N_PARTICIPANTS - 4, N_PARTICIPANTS, cap])

    # audio + bundle
    samples = {}
    if not args.skip_audio:
        from generation.audio_processing import DC_POLICY_ID, LEVEL_POLICY_ID, apply_level, audio_metrics, policy_definition
        from generation.corpus_audio import load_audio
        man = pd.read_parquet(ROOT / "data/raw/corpus_v4/manifest.parquet").set_index("sample_id")
        adir = audio_root / "audio"
        adir.mkdir(parents=True)
        entries = [(r.main_sound_id, r.sample_id, bool(r.is_anchor), r.pilot_sound_id if r.is_anchor else None)
                   for r in chosen.itertuples()]
        entries += [(f"sound_{N_SOUNDS + i + 1:03d}", p["source_sample_id"], False, f"sound_{65 + i:03d}")
                    for i, p in enumerate(practice_src)]
        anchor_match = 0
        for sid, src, is_anchor, pilot_id in entries:
            row = man.loc[src].to_dict()
            row["sample_id"] = src
            audio, _ = load_audio(row, verify=True)
            audio = np.asarray(audio, dtype=np.float64)
            before = audio_metrics(audio)
            gain = target_rms / before["held_rms"]
            adjusted = apply_level(audio, gain, input_policy_id=DC_POLICY_ID, peak_ceiling=ceiling)
            fpath, ppath = adir / f"{sid}_features.wav", adir / f"{sid}.wav"
            sf.write(fpath, adjusted, 44100, subtype="FLOAT")
            sf.write(ppath, adjusted, 44100, subtype="PCM_16")
            if pilot_id and sha(ppath) == bundle["samples"][pilot_id]["playback_sha256"]:
                anchor_match += 1
            params = {p: float(row[p + "_normalized"]) for p in PARAMS}
            samples[sid] = dict(sample_id=sid, source_sample_id=src, source_path=row["raw_audio_path"],
                                source_sha256=row["raw_audio_sha256"], parameters=params,
                                playback_path=f"audio/{ppath.name}", playback_sha256=sha(ppath),
                                feature_path=f"audio/{fpath.name}", feature_sha256=sha(fpath), gain=gain,
                                gain_db=20 * math.log10(gain), before_level=before, after_level=audio_metrics(adjusted),
                                policy_ids=[DC_POLICY_ID, LEVEL_POLICY_ID], pilot_sound_id=pilot_id,
                                role="practice" if int(sid[-3:]) > N_SOUNDS else ("anchor" if is_anchor else "new"))
        decisions["anchor_and_practice_playback_identical_to_pilot"] = f"{anchor_match}/{N_ANCHORS + 3}"
        pilot_dir = args.pilot_bundle.parent
        for h in bundle["headphones"]:
            shutil.copy2(pilot_dir / "audio" / h["path"], adir / h["path"])
        shutil.copy2(pilot_dir / "audio" / bundle["calibration"]["path"], adir / bundle["calibration"]["path"])
        level = dict(bundle["level_policy"], gains=[samples[s]["gain"] for s in samples],
                     note="Target RMS and peak ceiling inherited unchanged from the pilot bundle")
        main_bundle = dict(study_id="c1_main_v1", schema_version=1, rehearsal=simulated, version=args.version,
                           status=decisions["status"], dataset_name=recipe["dataset_name"],
                           source_manifest="data/raw/corpus_v4/manifest.parquet",
                           source_manifest_sha256=sha(ROOT / "data/raw/corpus_v4/manifest.parquet"),
                           feature_version=FEATURE_VERSION, preparation_sha256=sha(Path(__file__)),
                           pilot_bundle_sha256=sha(args.pilot_bundle), dc_policy=policy_definition(), level_policy=level,
                           selection=dict(method="pilot anchors + greedy maximin over parameter/acoustic/predicted-descriptor "
                                                 "blocks, weak-support bonus, quota repair",
                                          eligible_count=int(len(pool)), corpus_count=int(len(corpus)),
                                          exclusion_counts=exclusion_counts, study_sound_count=N_SOUNDS, anchors=N_ANCHORS,
                                          practice_count=3, note="Diversity/coverage heuristic; not perceptual or full-domain coverage"),
                           samples=samples, assignments=blocks, headphones=bundle["headphones"],
                           calibration=bundle["calibration"], headphone_pass_count=bundle["headphone_pass_count"],
                           headphone_trial_count=bundle["headphone_trial_count"],
                           assignment_version=f"{S}_unique_{HIDDEN_REPEATS}_repeats_prefix_balanced_v1",
                           assignment_plan=dict(target_completions=N_PARTICIPANTS, capacity=cap, unique_per_person=S,
                                                repeats_per_person=HIDDEN_REPEATS, practice_per_person=3,
                                                break_after_rated=decisions["break_after_rated"],
                                                completed_prefix_coverage=decisions["prefix_coverage"],
                                                note="Issue blocks in order and refill any non-completed block."))
        (audio_root / "bundle.json").write_text(json.dumps(main_bundle, indent=2) + "\n", encoding="utf-8")
        decisions["bundle"] = rel(audio_root / "bundle.json")
    (out / "assignments.json").write_text(json.dumps(blocks, indent=1), encoding="utf-8")

    # draft protocol config
    cfg = json.loads(json.dumps(pilot_cfg))
    total = 3 + S + HIDDEN_REPEATS
    cfg.update(protocol_version=f"c1_main_{datetime.now(timezone.utc):%Y-%m-%d}_{S}unique_{HIDDEN_REPEATS}rep_DRAFT",
               information_version=f"c1_main_information_{S}unique_DRAFT", target_participants=N_PARTICIPANTS,
               assignment_capacity=cap, break_after_rated=decisions["break_after_rated"], hidden_repeats=HIDDEN_REPEATS,
               unique_sounds_per_person=S, institutional_review_status="pending", rehearsal_completed=False,
               level_policy_listening_checked=False)
    cfg["information"][0] = (f"You will listen to {S} different synthesizer sounds, plus {HIDDEN_REPEATS} that may be played again, "
                             "and rate four aspects of their character: brightness, roughness, percussiveness and sustainedness.")
    cfg["information"][1] = (f"There are 3 practice sounds followed by {S + HIDDEN_REPEATS} study presentations, with a break after "
                             f"presentation {decisions['break_after_rated']}. Setup and a headphone check come first. Allow roughly "
                             f"{round(decisions['predicted_median_session_min'])}-{round(decisions['predicted_median_session_min']) + 5} minutes.")
    for t, st in decisions["descriptor_status"].items():
        if st["action"] != "retain_unchanged":
            cfg.setdefault("descriptor_review_required", []).append(dict(id=t, flags=st["flags"]))
    (out / "c1_main_protocol_DRAFT.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    decisions.update(version=args.version, created_utc=f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}", seed=SEED,
                     feature_version=FEATURE_VERSION, weak_support_threshold=support_threshold,
                     rules=dict(MAX_MEDIAN_SESSION_MIN=args.max_session_min, TERMS_UNCLEAR_FEEDBACK_LIMIT=TERMS_UNCLEAR_FEEDBACK_LIMIT, MIN_LISTENERS=MIN_LISTENERS,
                                TOO_LONG_FEEDBACK_LIMIT=TOO_LONG_FEEDBACK_LIMIT, UNCLEAR_REVISE=UNCLEAR_REVISE,
                                ICC_REVISE=ICC_REVISE, REDUNDANT_R=REDUNDANT_R, LOW_SPREAD_IQR=LOW_SPREAD_IQR,
                                TARGET_RELIABILITY=TARGET_RELIABILITY, QUOTAS=QUOTAS,
                                WEAK_SUPPORT_QUANTILE=WEAK_SUPPORT_QUANTILE, WEAK_SUPPORT_BONUS=WEAK_SUPPORT_BONUS),
                     corpus_exclusions=exclusion_counts, eligible_candidates=int(len(pool)),
                     selected_anchor_pilot_ids=anchor_ids, selected_weak_support=int(chosen.weak_support.sum()), log=log)
    (out / "decisions.json").write_text(json.dumps(decisions, indent=2, default=float), encoding="utf-8")
    print(json.dumps({k: decisions[k] for k in ("status", "unique_per_person", "min_listeners_per_sound",
                                                 "predicted_median_session_min", "assignment_capacity", "eligible_candidates",
                                                 "selected_weak_support", "prefix_coverage")}, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
