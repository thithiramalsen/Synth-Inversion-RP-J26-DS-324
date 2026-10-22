"""C3 human study (H3) - frozen selection rule and counterbalancing.

Each scored case shows a target sound and two blinded sets of k sounds: the plain top-k and
the C3 (MMR) set, built from the same audio shortlist. Participants rate how close each sound
is to the target and compare the two sets. Selection and counterbalancing never use any
human response or any judgement of which set looks better.
"""
from __future__ import annotations

import random

VERSION = "c3-human-v2"  # v1 used a provisional operating point (lambda 0.8); v2 uses the Phase 7 result
SEED = 20261022
TARGET = 12          # completed participants planned (formative, not a power claim)
CAP = 16             # maximum enrolments, including withdrawals and failed setup checks
N_SCORED = 8
CANDIDATE_POOL = 40  # seeded validation targets screened, in order, for eligibility
METHODS = ("topk", "mmr")

# Operating point selected on validation data in Phase 7 (D-018). It must equal the values in
# docs/PREREGISTRATION.md; if the preregistration changes them, build a new study version.
OPERATING_POINT = {
    "representation": "mfcc26",
    "pool_size": 100,
    "k": 5,
    "lam": 0.5,
    "relevance_scaling": "none",
    "status": "Phase 7 validation-selected (D-018); must match PREREGISTRATION.md",
}

NAMES = (
    "wave_frame", "bend_amount", "filter_cutoff", "filter_resonance", "filter_drive",
    "amp_attack", "amp_decay", "amp_sustain", "amp_release", "filter_env_amount",
    "filter_env_attack", "filter_env_decay", "filter_env_sustain",
)
LABELS = (
    "Wave shape", "Wave bend", "Filter cutoff", "Filter resonance", "Filter drive",
    "Volume attack", "Volume decay", "Volume sustain", "Volume release",
    "Filter-envelope amount", "Filter-envelope attack", "Filter-envelope decay", "Filter-envelope sustain",
)
CONSENT = ("adult", "english", "synth_experience", "information_read", "voluntary", "coded_data")

CLOSENESS = (1, 2, 3, 4, 5)
SET_CHOICES = ("A", "B", "no_difference", "cannot_judge")
SET_QUESTIONS = ("useful_starting_points", "closer_overall", "more_different_by_ear")


def eligible(top_ids: list[str], mmr_ids: list[str]) -> tuple[bool, str]:
    """A case is comparable only if the two sets differ by at least one sound."""
    if len(set(top_ids)) != len(top_ids) or len(set(mmr_ids)) != len(mmr_ids):
        return False, "duplicate sound inside a set"
    if set(top_ids) == set(mmr_ids):
        return False, "identical sets: nothing to compare"
    return True, ""


def case_order() -> list[int]:
    """Fixed seeded permutation of the eight scored cases (0-based)."""
    order = list(range(N_SCORED))
    random.Random(SEED).shuffle(order)
    return order


def assignment(slot: int) -> list[dict]:
    """Case order and which method is shown as Set A for one participant slot.

    Slots come in complementary pairs (2j, 2j + 1): same case order, opposite labels.
    Every participant sees MMR as Set A in exactly four cases. Over twelve completions each
    case shows MMR as A six times and as B six times. Case order rotates between pairs.
    """
    if type(slot) is not int or not 0 <= slot < TARGET:
        raise ValueError(f"Assignment slot must be 0-{TARGET - 1}")
    base = case_order()
    shift = slot // 2
    order = base[shift:] + base[:shift]
    return [{"case_id": f"case_{case + 1:02d}",
             "set_a": "mmr" if ((position % 2 == 0) != (slot % 2 == 1)) else "topk"}
            for position, case in enumerate(order)]


def display_order(case_id: str, n_sounds: int) -> list[int]:
    """Fixed per-case shuffle used to number sounds and order them inside each set."""
    order = list(range(n_sounds))
    random.Random(f"{SEED}:{case_id}").shuffle(order)
    return order
