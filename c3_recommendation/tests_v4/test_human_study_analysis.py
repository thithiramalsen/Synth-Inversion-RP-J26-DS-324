"""Perceptual closeness analysis: recovers known simulated effects; writes the report."""

import json

import numpy as np
import pytest

from human_study.analysis import (
    analyze, bootstrap_ci, participant_closeness, primary_outcome, ratings_table, simulate_sessions,
)
from human_study.design import EQUIVALENCE_MARGIN, N_SCORED, VERSION


@pytest.fixture(scope="module")
def bundle():
    rng = np.random.default_rng(3)
    cases, provenance = [], []
    for case_id in [*[f"case_{i:02d}" for i in range(1, N_SCORED + 1)], "practice"]:
        top, mmr = [1, 2, 3, 4, 5], [1, 2, 6, 7, 8]
        sounds = []
        for n in range(1, 9):
            relevance = float(rng.uniform(0.86, 0.99))
            sounds.append({"number": n, "sample_id": f"{case_id}_{n}", "relevance": relevance,
                           "audio_rank": int(np.ceil((1 - relevance) * 100)), "in_topk": n in top, "in_mmr": n in mmr})
        cases.append({"case_id": case_id, "sounds": [{"number": s["number"]} for s in sounds],
                      "sets": {"topk": top, "mmr": mmr}})
        provenance.append({"case_id": case_id, "sounds": sounds})
    return {"version": VERSION, "cases": cases, "provenance": provenance}


def test_no_effect_is_heard_as_close(bundle):
    people = participant_closeness(ratings_table(simulate_sessions(bundle, 60, c3_effect=0.0), bundle))
    result = primary_outcome(people)
    assert result["n_participants"] == 60
    assert result["ci95"][0] > -EQUIVALENCE_MARGIN
    assert result["decision"].startswith("C3 picks heard as close")


def test_large_negative_effect_is_detected(bundle):
    people = participant_closeness(ratings_table(simulate_sessions(bundle, 60, c3_effect=-1.5), bundle))
    result = primary_outcome(people)
    # The 1-5 scale floor shrinks the injected -1.5 shift, but it must stay clearly beyond the margin.
    assert result["mean"] < -EQUIVALENCE_MARGIN and result["ci95"][1] < 0
    assert result["decision"].startswith("not shown to be within the margin")


def test_cannot_judge_excluded_and_small_sample_flagged(bundle):
    sessions = simulate_sessions(bundle, 1, c3_effect=0.0)
    for response in sessions[0]["responses"]:
        response["answers"]["closeness"]["1"] = "cannot_judge"
    ratings = ratings_table(sessions, bundle)
    assert ratings.loc[ratings.number == 1, "rating"].isna().all()
    assert ratings["cannot_judge"].sum() >= N_SCORED
    result = primary_outcome(participant_closeness(ratings))
    assert result["ci95"] is None and result["decision"].startswith("insufficient data")


def test_incomplete_sessions_are_ignored(bundle):
    sessions = simulate_sessions(bundle, 3)
    sessions[1]["phase"] = "withdrawn"
    assert ratings_table(sessions, bundle)["code"].nunique() == 2


def test_bootstrap_ci_contains_mean_and_is_seeded():
    values = [0.1, -0.2, 0.3, 0.0, 0.2]
    ci = bootstrap_ci(values)
    assert ci[0] <= np.mean(values) <= ci[1] and ci == bootstrap_ci(values)
    assert bootstrap_ci([0.5]) is None


def test_analyze_writes_report_and_guards(tmp_path, bundle):
    out = tmp_path / "analysis"
    result = analyze(simulate_sessions(bundle, 12, c3_effect=0.0), bundle, out, "simulated")
    for name in ("REPORT.md", "analysis.json", "ratings_long.csv", "participant_closeness.csv", "per_case.csv"):
        assert (out / name).exists()
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "SIMULATED DATA" in report and "Primary outcome" in report
    assert json.loads((out / "analysis.json").read_text())["not_research_findings"] is True
    assert result["model_agreement"]["relevance_vs_rating"]["mean_spearman"] > 0.3  # ratings follow relevance
    with pytest.raises(ValueError, match="fresh"):
        analyze(simulate_sessions(bundle, 2), bundle, out, "simulated")
    with pytest.raises(ValueError, match="disabled"):
        analyze(simulate_sessions(bundle, 2), bundle, tmp_path / "other", "research")
