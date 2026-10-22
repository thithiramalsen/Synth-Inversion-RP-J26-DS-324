"""Freeze selection and counterbalancing independently of measured quality."""
import random

VERSION = "c2-human-v1"
SEED = 20261018
TARGET = 12
CAP = 16
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


def select_cases(frame):
    """First eight fixed ranks for tasks; ninth for practice. Never silently replace."""
    if frame.sample_id.duplicated().any() or frame.diagnostic_rank.duplicated().any():
        raise ValueError("Duplicate identities or ranks")
    if not (frame.split == "validation").all() or not (frame.validation_role == "reliability").all():
        raise ValueError("Only reliability-validation diagnostics are eligible")
    selected = frame.sort_values("diagnostic_rank").head(9)
    if selected.diagnostic_rank.tolist() != list(range(9)):
        raise ValueError("Need predetermined ranks 0–8, with no missing rank")
    return selected


def assignment(slot):
    """Complementary pairs give each case six exposures in each condition at N=12."""
    if type(slot) is not int or not 0 <= slot < TARGET:
        raise ValueError("Assignment slot must be 0–11")
    base = list(range(8))
    random.Random(SEED).shuffle(base)
    shift = slot // 2
    order = base[shift:] + base[:shift]
    return [{"case_id": f"case_{case + 1:02d}",
             "condition": "with" if ((position < 4) == (slot % 2 == 0)) else "without"}
            for position, case in enumerate(order)]
