"""Perceptual closeness evaluation for the C3 human study (analysis plan frozen in D-020).

Question: do people hear C3's more varied picks as being as close to the target as the plain
top-k picks?

Primary outcome (participant level): mean closeness rating of sounds only in the C3 set minus
sounds only in the top-k set. C3's picks are "heard as close as the top-k" when the lower bound
of the 95% participant bootstrap CI is above -EQUIVALENCE_MARGIN (0.5 rating points).

Secondary: closeness levels per group (are the suggestions close at all?), agreement between
the model's audio relevance and human ratings, set-level choices, per-case results.

``simulate_sessions`` makes clearly labelled fake sessions with a known effect, only to check
the software. Simulated output is never a result.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon

from .design import (
    ANALYSIS_BOOTSTRAP, CLOSE_RATING, EQUIVALENCE_MARGIN, N_SCORED, SEED, SET_CHOICES, SET_QUESTIONS, assignment,
)

GROUPS = ("topk_only", "mmr_only", "both")
GROUP_LABELS = {"topk_only": "Top-k only", "mmr_only": "C3 only", "both": "In both sets"}


def chosen_method(answer: str, set_a: str) -> str:
    """Map a Set A / Set B answer back to the method shown under that label."""
    if answer == "A":
        return set_a
    if answer == "B":
        return "mmr" if set_a == "topk" else "topk"
    return answer  # no_difference / cannot_judge


def bootstrap_ci(values, draws: int = ANALYSIS_BOOTSTRAP, seed: int = SEED):
    """Participant-level percentile bootstrap 95% CI of the mean; None with fewer than 2 values."""
    values = np.asarray([v for v in values if v is not None and not np.isnan(v)], dtype=float)
    if len(values) < 2:
        return None
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(draws, len(values)))].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return [float(low), float(high)]


# ---------------------------------------------------------------------- tables
def ratings_table(sessions: list[dict], bundle: dict) -> pd.DataFrame:
    """One row per (participant, case, sound) for completed sessions, joined to private provenance."""
    sound_info = {(p["case_id"], s["number"]): s for p in bundle["provenance"] for s in p["sounds"]}
    rows = []
    for session in sessions:
        if session["phase"] != "complete":
            continue
        for response in session["responses"]:
            for number, rating in response["answers"]["closeness"].items():
                info = sound_info[(response["case_id"], int(number))]
                rows.append({"code": session["code"], "slot": session["slot"], "case_id": response["case_id"],
                             "position": response["position"], "number": int(number),
                             "group": response["membership"][number],
                             "rating": float(rating) if type(rating) is int else np.nan,
                             "cannot_judge": rating == "cannot_judge",
                             "relevance": info["relevance"], "audio_rank": info["audio_rank"],
                             "sample_id": info["sample_id"]})
    return pd.DataFrame(rows)


def participant_closeness(ratings: pd.DataFrame) -> pd.DataFrame:
    """Per participant: mean rating per group, valid counts and the C3-only minus top-k-only difference."""
    rows = []
    for code, frame in ratings.groupby("code", sort=True):
        row = {"code": code}
        for group in GROUPS:
            values = frame.loc[frame["group"] == group, "rating"].dropna()
            row[f"mean_{group}"] = float(values.mean()) if len(values) else np.nan
            row[f"n_{group}"] = int(len(values))
            row[f"share_close_{group}"] = float((values >= CLOSE_RATING).mean()) if len(values) else np.nan
        row["cannot_judge"] = int(frame["cannot_judge"].sum())
        row["c3_minus_topk"] = row["mean_mmr_only"] - row["mean_topk_only"]
        rows.append(row)
    return pd.DataFrame(rows)


def per_case(ratings: pd.DataFrame) -> pd.DataFrame:
    table = ratings.groupby(["case_id", "group"])["rating"].agg(["mean", "count"]).unstack("group")
    table.columns = [f"{stat}_{group}" for stat, group in table.columns]
    return table.reset_index()


# ---------------------------------------------------------------------- outcomes
def primary_outcome(people: pd.DataFrame, margin: float = EQUIVALENCE_MARGIN) -> dict:
    diffs = people["c3_minus_topk"].dropna().to_numpy()
    ci = bootstrap_ci(diffs)
    if ci is None:
        decision = "insufficient data (fewer than 2 participants with both groups rated)"
    elif ci[0] > -margin:
        decision = "C3 picks heard as close as the top-k (CI lower bound above -margin)"
    else:
        decision = "not shown to be within the margin (CI lower bound at or below -margin)"
    test = None
    if len(diffs) >= 6 and np.any(diffs != 0):
        stat = wilcoxon(diffs)
        test = {"wilcoxon_statistic": float(stat.statistic), "p_value": float(stat.pvalue), "exploratory": True}
    return {"definition": "per participant: mean rating of C3-only sounds minus top-k-only sounds",
            "margin": margin, "n_participants": int(len(diffs)),
            "mean": float(diffs.mean()) if len(diffs) else None,
            "median": float(np.median(diffs)) if len(diffs) else None,
            "ci95": ci, "decision": decision, "difference_from_zero_test": test}


def closeness_levels(people: pd.DataFrame) -> dict:
    """Are the suggestions close at all? Mean of participant means and share of 4-5 ratings."""
    out = {}
    for group in GROUPS:
        means = people[f"mean_{group}"].dropna()
        shares = people[f"share_close_{group}"].dropna()
        out[group] = {"label": GROUP_LABELS[group], "n_participants": int(len(means)),
                      "mean_rating": float(means.mean()) if len(means) else None, "ci95": bootstrap_ci(means),
                      f"share_rated_{CLOSE_RATING}_or_5": float(shares.mean()) if len(shares) else None}
    return out


def model_agreement(ratings: pd.DataFrame) -> dict:
    """Within-participant Spearman correlation of model relevance (and shortlist rank) with ratings."""
    rho_rel, rho_rank = [], []
    for _, frame in ratings.dropna(subset=["rating"]).groupby("code"):
        if frame["rating"].nunique() > 1 and len(frame) >= 5:
            rho_rel.append(float(spearmanr(frame["relevance"], frame["rating"]).statistic))
            rho_rank.append(float(spearmanr(frame["audio_rank"], frame["rating"]).statistic))
    return {"relevance_vs_rating": {"n_participants": len(rho_rel), "mean_spearman": float(np.mean(rho_rel)) if rho_rel else None,
                                    "ci95": bootstrap_ci(rho_rel)},
            "shortlist_rank_vs_rating": {"n_participants": len(rho_rank), "mean_spearman": float(np.mean(rho_rank)) if rho_rank else None,
                                         "ci95": bootstrap_ci(rho_rank)},
            "interpretation": "positive relevance correlation = the model's audio relevance agrees with human closeness"}


def set_choices(sessions: list[dict]) -> dict:
    completed = [s for s in sessions if s["phase"] == "complete"]
    out = {}
    for question in SET_QUESTIONS:
        shares, totals = [], Counter()
        for session in completed:
            counts = Counter(chosen_method(r["answers"][question], r["set_a"]) for r in session["responses"])
            totals.update(counts)
            decisive = counts["mmr"] + counts["topk"]
            if decisive:
                shares.append(counts["mmr"] / decisive)
        out[question] = {"answer_counts": {k: int(totals.get(k, 0)) for k in ("mmr", "topk", "no_difference", "cannot_judge")},
                         "n_participants_decisive": len(shares),
                         "mean_c3_share_of_decisive": float(np.mean(shares)) if shares else None,
                         "ci95": bootstrap_ci(shares), "no_preference_value": 0.5}
    return out


# ---------------------------------------------------------------------- report
def _plots(people: pd.DataFrame, levels: dict, primary: dict, out_dir: Path, label: str) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    made = []
    ink, grey = "#1a1a1a", "#8a8a8a"

    fig, ax = plt.subplots(figsize=(6.5, 3.2), dpi=150)
    groups = [g for g in GROUPS if levels[g]["mean_rating"] is not None]
    for i, group in enumerate(groups):
        values = people[f"mean_{group}"].dropna().to_numpy()
        ax.scatter(np.full(len(values), i) + np.linspace(-0.12, 0.12, len(values)), values, s=12, color=grey, zorder=2)
        level = levels[group]
        if level["ci95"]:
            ax.errorbar([i], [level["mean_rating"]], yerr=[[level["mean_rating"] - level["ci95"][0]], [level["ci95"][1] - level["mean_rating"]]],
                        fmt="s", color=ink, markersize=6, capsize=4, zorder=3)
    ax.set_xticks(range(len(groups)), [GROUP_LABELS[g] for g in groups], fontsize=9)
    ax.set_ylim(1, 5.2)
    ax.set_ylabel("closeness to target (1–5)", fontsize=9)
    ax.set_title(f"How close each group of sounds was heard ({label})", fontsize=10, loc="left")
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.6); ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout(); fig.savefig(out_dir / "closeness_by_group.png"); plt.close(fig)
    made.append("closeness_by_group.png")

    diffs = people["c3_minus_topk"].dropna().to_numpy()
    if len(diffs):
        fig, ax = plt.subplots(figsize=(6.5, 2.6), dpi=150)
        ax.axvspan(-EQUIVALENCE_MARGIN, EQUIVALENCE_MARGIN, color="#eeeeee", zorder=0)
        ax.axvline(0, color=grey, linewidth=0.8)
        ax.axvline(-EQUIVALENCE_MARGIN, color=ink, linewidth=1, linestyle=(0, (3, 2)))
        ax.scatter(diffs, np.full(len(diffs), 0.0) + np.linspace(-0.25, 0.25, len(diffs)), s=14, color=grey, zorder=2)
        if primary["ci95"]:
            ax.errorbar([primary["mean"]], [0.6], xerr=[[primary["mean"] - primary["ci95"][0]], [primary["ci95"][1] - primary["mean"]]],
                        fmt="s", color=ink, markersize=6, capsize=4, zorder=3)
        ax.annotate(f"−{EQUIVALENCE_MARGIN:g} margin", (-EQUIVALENCE_MARGIN, 0.95), xytext=(4, 0), textcoords="offset points", fontsize=8)
        ax.set_yticks([])
        ax.set_ylim(-0.5, 1.1)
        ax.set_xlabel("C3-only minus top-k-only closeness, per participant (points)", fontsize=9)
        ax.set_title(f"Primary outcome: mean and 95% CI above, participants below ({label})", fontsize=10, loc="left")
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        fig.tight_layout(); fig.savefig(out_dir / "primary_outcome.png"); plt.close(fig)
        made.append("primary_outcome.png")
    return made


def _fmt(value, pct=False):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "–"
    return f"{value:.0%}" if pct else f"{value:.2f}"


def _ci(ci):
    return "–" if not ci else f"[{ci[0]:.2f}, {ci[1]:.2f}]"


def write_report(path: Path, result: dict) -> None:
    p, levels, agree, choices = result["primary"], result["closeness_levels"], result["model_agreement"], result["set_choices"]
    banner = {"simulated": "SIMULATED DATA — software check only. These numbers are not results.",
              "demo": "DEMO DATA — presentation run; the headphone check may have been skipped. Not results.",
              "rehearsal": "REHEARSAL DATA — excluded from research. These numbers are not findings."}.get(result["mode"], "")
    lines = [f"# C3 perceptual closeness evaluation — {result['mode']}", "",
             f"> {banner}" if banner else "", "",
             f"Generated {result['generated_utc']} · study {result['study_version']} · "
             f"{result['completed_participants']} completed participants · {result['rated_sounds']} sound ratings "
             f"({result['cannot_judge']} Cannot judge). Sessions excluded because the setup check was skipped: "
             f"{result['excluded_screen_skipped']}.", "",
             "## 1. Primary outcome: are C3's picks heard as close as the top-k?", "",
             f"Per participant, mean closeness of sounds only in the C3 set minus sounds only in the top-k set "
             f"(1–5 scale). Margin: {p['margin']:g} points.", "",
             "| Participants | Mean difference | Median | 95% CI | Decision |", "|---|---|---|---|---|",
             f"| {p['n_participants']} | {_fmt(p['mean'])} | {_fmt(p['median'])} | {_ci(p['ci95'])} | {p['decision']} |", ""]
    if p["difference_from_zero_test"]:
        t = p["difference_from_zero_test"]
        lines += [f"Exploratory Wilcoxon signed-rank test of the difference against 0: p = {t['p_value']:.3f}.", ""]
    lines += ["## 2. Are the suggestions close to the target at all?", "",
              f"| Group | Participants | Mean rating | 95% CI | Share rated {CLOSE_RATING}–5 |", "|---|---|---|---|---|"]
    for group in GROUPS:
        level = levels[group]
        lines.append(f"| {level['label']} | {level['n_participants']} | {_fmt(level['mean_rating'])} | {_ci(level['ci95'])} | "
                     f"{_fmt(level[f'share_rated_{CLOSE_RATING}_or_5'], pct=True)} |")
    lines += ["", "## 3. Does the model's audio relevance agree with human ears?", "",
              "| Comparison | Participants | Mean Spearman ρ | 95% CI |", "|---|---|---|---|",
              f"| Model relevance vs rating | {agree['relevance_vs_rating']['n_participants']} | {_fmt(agree['relevance_vs_rating']['mean_spearman'])} | {_ci(agree['relevance_vs_rating']['ci95'])} |",
              f"| Shortlist rank vs rating | {agree['shortlist_rank_vs_rating']['n_participants']} | {_fmt(agree['shortlist_rank_vs_rating']['mean_spearman'])} | {_ci(agree['shortlist_rank_vs_rating']['ci95'])} |",
              "", "A positive relevance correlation (and a negative rank correlation) means sounds the model ranks as closer "
              "are also heard as closer.", "",
              "## 4. Set-level choices", "",
              "Share of each participant's decisive answers (Set A or B) that chose the C3 set; 0.5 means no preference.", "",
              "| Question | C3 | Top-k | No difference | Cannot judge | Mean C3 share | 95% CI |", "|---|---|---|---|---|---|---|"]
    names = {"useful_starting_points": "More useful, different starting points", "closer_overall": "Closer to the target overall",
             "more_different_by_ear": "More different from each other by ear"}
    for question, c in choices.items():
        n = c["answer_counts"]
        lines.append(f"| {names[question]} | {n['mmr']} | {n['topk']} | {n['no_difference']} | {n['cannot_judge']} | "
                     f"{_fmt(c['mean_c3_share_of_decisive'])} | {_ci(c['ci95'])} |")
    lines += ["", "## 5. Notes", "",
              "- Unit of analysis: the participant. Cases and sounds are repeated measurements.",
              "- Cannot judge is excluded from means, never counted as a rating.",
              f"- Conditional on {N_SCORED} validation cases and the study's operating point; small-N intervals are unstable.",
              "- Figures: `closeness_by_group.png`, `primary_outcome.png`. Tables: `participant_closeness.csv`, `per_case.csv`.", ""]
    path.write_text("\n".join(line for line in lines if line is not None) + "\n", encoding="utf-8")


def analyze(sessions: list[dict], bundle: dict, out_dir: Path, mode: str) -> dict:
    if mode not in {"simulated", "rehearsal", "demo"}:
        raise ValueError("Research collection is disabled; only simulated, rehearsal or demo data can be analysed")
    # A skipped headphone check (demo mode) invalidates closeness ratings outside a demo report.
    skipped = [s for s in sessions if s.get("screen_skipped")]
    if mode != "demo":
        sessions = [s for s in sessions if not s.get("screen_skipped")]
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise ValueError("Use a fresh output folder; preserve previous analyses")
    ratings = ratings_table(sessions, bundle)
    if ratings.empty:
        raise ValueError("No completed sessions to analyse")
    people = participant_closeness(ratings)
    primary = primary_outcome(people)
    levels = closeness_levels(people)
    result = {"mode": mode, "study_version": bundle["version"], "generated_utc": datetime.now(timezone.utc).isoformat(),
              "completed_participants": int(people.shape[0]), "rated_sounds": int(ratings["rating"].notna().sum()),
              "cannot_judge": int(ratings["cannot_judge"].sum()),
              "excluded_screen_skipped": 0 if mode == "demo" else len(skipped),
              "primary": primary, "closeness_levels": levels,
              "model_agreement": model_agreement(ratings), "set_choices": set_choices(sessions),
              "analysis_plan": "D-020", "not_research_findings": True}
    out_dir.mkdir(parents=True)
    ratings.to_csv(out_dir / "ratings_long.csv", index=False)
    people.to_csv(out_dir / "participant_closeness.csv", index=False, float_format="%.4f")
    per_case(ratings).to_csv(out_dir / "per_case.csv", index=False, float_format="%.4f")
    result["figures"] = _plots(people, levels, primary, out_dir, mode)
    (out_dir / "analysis.json").write_text(json.dumps(result, indent=2, allow_nan=False, default=float) + "\n", encoding="utf-8")
    write_report(out_dir / "REPORT.md", result)
    return result


# ---------------------------------------------------------------------- simulation (software check)
def simulate_sessions(bundle: dict, n_participants: int = 12, c3_effect: float = 0.0, seed: int = SEED) -> list[dict]:
    """Fake completed sessions for checking the software. Labelled simulated; never a result.

    Each fake rating = 1 + 4 x (relevance - 0.85) / 0.15, clipped, plus a participant bias, noise
    and ``c3_effect`` points for C3-only sounds. Because C3-only sounds sit deeper in the
    shortlist (lower relevance), the simulated C3-only minus top-k-only difference is negative
    even at ``c3_effect = 0``: that is an ASSUMPTION of this simulator (people track MFCC
    relevance steeply), not a prediction. Real responses decide what people actually hear.
    """
    rng = random.Random(seed)
    sounds = {(p["case_id"], s["number"]): s for p in bundle["provenance"] for s in p["sounds"]}
    cases = {c["case_id"]: c for c in bundle["cases"]}
    sessions = []
    for person in range(n_participants):
        slot = person % 12
        bias = rng.gauss(0, 0.4)
        responses = []
        for position, task in enumerate(assignment(slot), start=1):
            case = cases[task["case_id"]]
            top, mmr = set(case["sets"]["topk"]), set(case["sets"]["mmr"])
            membership, closeness = {}, {}
            for sound in case["sounds"]:
                n = sound["number"]
                group = "both" if n in top and n in mmr else ("topk_only" if n in top else "mmr_only")
                membership[str(n)] = group
                rel = sounds[(task["case_id"], n)]["relevance"]
                score = 1 + 4 * min(1.0, max(0.0, (rel - 0.85) / 0.15)) + bias + rng.gauss(0, 0.6)
                score += c3_effect if group == "mmr_only" else 0.0
                closeness[str(n)] = "cannot_judge" if rng.random() < 0.03 else int(min(5, max(1, round(score))))
            answers = {"closeness": closeness, "confidence": rng.randint(2, 5), "reason": ""}
            for question in SET_QUESTIONS:
                answers[question] = rng.choice(SET_CHOICES)
            responses.append({"case_id": task["case_id"], "set_a": task["set_a"], "membership": membership,
                              "answers": answers, "position": position})
        sessions.append({"code": f"SIM-{person + 1:03d}", "slot": slot, "phase": "complete", "mode": "simulated",
                         "responses": responses, "feedback": {"knob_bars": 3, "length": "about_right", "comment": ""}})
    return sessions
