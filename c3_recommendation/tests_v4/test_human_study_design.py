"""C3 human study: frozen counterbalancing, eligibility and technical audio QA."""

from collections import Counter

import numpy as np
import pytest

from human_study.build import audio_problem
from human_study.design import N_SCORED, TARGET, assignment, display_order, eligible


def test_each_participant_sees_c3_as_set_a_in_half_the_cases():
    for slot in range(TARGET):
        plan = assignment(slot)
        assert plan == assignment(slot)
        assert sorted(p["case_id"] for p in plan) == [f"case_{i:02d}" for i in range(1, N_SCORED + 1)]
        assert Counter(p["set_a"] for p in plan) == {"mmr": 4, "topk": 4}


def test_each_case_shows_c3_as_a_and_b_equally_across_twelve():
    counts = Counter((p["case_id"], p["set_a"]) for slot in range(TARGET) for p in assignment(slot))
    assert set(counts.values()) == {TARGET // 2}


def test_complementary_pairs_swap_labels_and_keep_order():
    for pair in range(TARGET // 2):
        first, second = assignment(2 * pair), assignment(2 * pair + 1)
        assert [p["case_id"] for p in first] == [p["case_id"] for p in second]
        assert all(a["set_a"] != b["set_a"] for a, b in zip(first, second))


def test_invalid_slot_rejected():
    for slot in (-1, TARGET, 1.0):
        with pytest.raises(ValueError):
            assignment(slot)


def test_eligibility_rules():
    assert eligible(["a", "b", "c"], ["a", "b", "d"]) == (True, "")
    assert eligible(["a", "b", "c"], ["c", "b", "a"])[0] is False
    assert eligible(["a", "a", "c"], ["a", "b", "d"])[0] is False


def test_display_order_is_fixed_per_case_and_a_permutation():
    order = display_order("case_03", 7)
    assert sorted(order) == list(range(7))
    assert order == display_order("case_03", 7)


def test_audio_problem_flags_only_technical_failures():
    t = np.arange(44100) / 44100
    assert audio_problem(0.2 * np.sin(2 * np.pi * 440 * t)) == ""
    assert audio_problem(np.zeros(100)) == "silent"
    assert audio_problem(np.full(100, 1e-5)) == "silent"
    assert audio_problem(np.array([0.1, 1.0, -0.2])) == "clipped"
    assert audio_problem(np.array([0.1, np.nan])) == "non-finite samples"
