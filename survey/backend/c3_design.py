"""C3 study rules for the hosted rehearsal (copy of c3_recommendation/human_study/design.py).

The deployment image contains only survey/backend, so the frozen values are copied here.
survey/backend/tests/test_c3_hosted.py checks that they still equal the original.
"""
import random

VERSION = "c3-human-v2"
SEED = 20261022
TARGET = 12
CAP = 16
N_SCORED = 8
CLOSENESS = (1, 2, 3, 4, 5)
MAX_SCREEN_ATTEMPTS = 3
SET_CHOICES = ("A", "B", "no_difference", "cannot_judge")
SET_QUESTIONS = ("useful_starting_points", "closer_overall", "more_different_by_ear")
CONSENT = ("adult", "english", "synth_experience", "information_read", "voluntary", "coded_data")
OPERATING_POINT = {
    "representation": "mfcc26",
    "pool_size": 100,
    "k": 5,
    "lam": 0.5,
    "relevance_scaling": "none",
    "status": "Phase 7 validation-selected (D-018); must match PREREGISTRATION.md",
}


def case_order():
    order = list(range(N_SCORED))
    random.Random(SEED).shuffle(order)
    return order


def assignment(slot):
    """Complementary slot pairs: same case order, opposite Set A/B labels; C3 is Set A in 4 of 8."""
    if type(slot) is not int or not 0 <= slot < TARGET:
        raise ValueError(f"Assignment slot must be 0-{TARGET - 1}")
    base = case_order()
    shift = slot // 2
    order = base[shift:] + base[:shift]
    return [{"case_id": f"case_{case + 1:02d}",
             "set_a": "mmr" if ((position % 2 == 0) != (slot % 2 == 1)) else "topk"}
            for position, case in enumerate(order)]
