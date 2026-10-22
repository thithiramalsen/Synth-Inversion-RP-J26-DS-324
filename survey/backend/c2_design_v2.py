"""C2 v2: blinded listening first, display usefulness second. Rehearsal only."""
import random

from c2_design import CONSENT, NAMES, TARGET, assignment as frozen_assignment

VERSION = "c2-human-v2"
PROTOCOL = "c2-hosted-rehearsal-v2"
SEED = 20261022
CONTRACT = {
    "protocol": PROTOCOL,
    "seed": SEED,
    "source_bundle": "c2-human-v1",
    "selection": "unchanged diagnostic ranks 0-7; practice rank 8",
    "listening": {"cases": 8, "practice": 1, "parameters_visible": False,
                  "reliability_visible": False, "scale": [1, 5],
                  "endpoints": ["Not at all similar", "Very similar"],
                  "cannot_judge": True, "optional_comment": True},
    "display": {"cases": 8, "with": 4, "without": 4,
                "ratings": ["clarity", "usefulness"], "scale": [1, 5],
                "cannot_judge": True, "editing": False, "control_decisions": False},
    "comprehension": "once after all display ratings; meaning, guarantee, impossible",
    "audio_ratings_locked_before_any_display": True,
    "tau_z": 0.05,
    "research_collection_enabled": False,
}


def assignment(slot):
    display = frozen_assignment(slot)  # Retain the frozen 4/4 complementary allocation.
    listening = [task["case_id"] for task in display]
    random.Random(SEED + slot // 2).shuffle(listening)
    return {"listening": listening, "display": display}


def rating(value):
    return value == "cannot_judge" or (type(value) is int and 1 <= value <= 5)
