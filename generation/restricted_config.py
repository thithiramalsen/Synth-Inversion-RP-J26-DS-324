"""Twelve-control, one-oscillator candidate domain; bounds are not human-validated.

Keep the historical pilot_v1 profile and its artifacts unchanged. Any later change
to these bounds, rendering conditions or routing requires a new dataset version.
"""

from copy import deepcopy

from generation import params_config as legacy

PROJECT_ROOT = legacy.PROJECT_ROOT
DATASET_NAME = "restricted_v2"
SCHEMA_STATUS = "candidate_for_technical_characterization"
BASE_PRESET = PROJECT_ROOT / "generation/presets/base_restricted_v2.vital"
SOURCE_PRESET = PROJECT_ROOT / "generation/presets/basic_shapes_source_RP.vital"
PILOT_AUDIO_DIR = PROJECT_ROOT / "data/raw/audio" / DATASET_NAME
PILOT_MANIFEST_CSV = PROJECT_ROOT / "data/manifests" / f"{DATASET_NAME}.csv"
PILOT_MANIFEST_PARQUET = PILOT_MANIFEST_CSV.with_suffix(".parquet")

SAMPLE_RATE = 44_100
MIDI_NOTE = 60
VELOCITY = 0.80
NOTE_DURATION = 1.50
RENDER_DURATION = 3.00
PILOT_SAMPLE_COUNT = 1024
SAMPLING_SEED = 20260803

PARAMS = deepcopy(legacy.PARAMS)
# With Vital's calibrated quartic time scale, these maxima give approximately
# 0.480 s attack + 0.819 s decay, leaving a held segment before note-off at 1.5 s.
PARAMS["amp_attack"].update(max=0.35, description="Amplitude attack; candidate maximum about 0.480 s.")
PARAMS["amp_decay"].update(max=0.40, description="Amplitude decay; candidate maximum about 0.819 s.")
PARAMS.update({
    "filter_env_amount": {
        "control": "modulation_1_amount", "mode": "normalized", "min": 0.50, "max": 0.5625,
        "description": "ENV 2 -> cutoff, positive unipolar depth. Normalized 0.5 is ZERO; raw range 0 to 0.125. Verify nominal 0 to 16 semitones in characterization.",
    },
    "filter_env_attack": {
        "control": "env_2_attack", "mode": "normalized", "min": 0.05, "max": 0.35,
        "description": "Filter-envelope rise; candidate range about 0.0002 to 0.480 s.",
    },
    "filter_env_decay": {
        "control": "env_2_decay", "mode": "normalized", "min": 0.15, "max": 0.40,
        "description": "Filter-envelope fall toward sustain; candidate range about 0.0162 to 0.819 s.",
    },
    "filter_env_sustain": {
        "control": "env_2_sustain", "mode": "normalized", "min": 0.00, "max": 1.00,
        "description": "Held fraction of filter-envelope depth. At 1, decay is inactive; at zero depth all ENV 2 timing/level controls are inactive.",
    },
})

MODULATIONS = ({"source": "env_2", "destination": "filter_1_cutoff", "slot": 1},)
FIXED_CONTROLS = deepcopy(legacy.FIXED_CONTROLS)
FIXED_CONTROLS.update({
    "osc_1_phase": ("raw", 0.5),
    "env_1_delay": ("raw", 0.0), "env_1_hold": ("raw", 0.0),
    "env_1_attack_power": ("raw", 0.0), "env_1_decay_power": ("raw", -2.0),
    "env_1_release_power": ("raw", -2.0),
    "env_2_delay": ("raw", 0.0), "env_2_hold": ("raw", 0.0),
    "env_2_attack_power": ("raw", 0.0), "env_2_decay_power": ("raw", -2.0),
    "env_2_release": ("normalized", 0.30), "env_2_release_power": ("raw", -2.0),
    "modulation_1_bipolar": ("raw", 0.0), "modulation_1_bypass": ("raw", 0.0),
    "modulation_1_power": ("raw", 0.0), "modulation_1_stereo": ("raw", 0.0),
})

# Values for a usable, reproducible base patch; dataset rows override all twelve.
BASE_VALUES = {
    "wave_frame": 0.50, "filter_cutoff": 0.50, "filter_resonance": 0.20,
    "filter_drive": 0.0, "amp_attack": 0.10, "amp_decay": 0.30,
    "amp_sustain": 0.80, "amp_release": 0.30, "filter_env_amount": 0.53125,
    "filter_env_attack": 0.20, "filter_env_decay": 0.30, "filter_env_sustain": 0.40,
}
