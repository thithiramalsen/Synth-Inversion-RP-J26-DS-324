"""Thirteen-control candidate: keep both Bend and variable filter-envelope sustain.

Previous twelve-control profiles/presets remain available for comparison. The
dc_highpass_10hz_v1 policy is selected; integration and final bounds are pending.
This module does not process audio.
"""
from copy import deepcopy

from generation import bend_config as previous
from generation import restricted_config as architecture_a

PROJECT_ROOT = previous.PROJECT_ROOT
DATASET_NAME = "restricted_bend_sustain_v4"
SCHEMA_STATUS = "selected_13_controls_dc_policy_selected_integration_pending"
BASE_PRESET = PROJECT_ROOT / "generation/presets/base_restricted_bend_sustain_v4.vital"
SOURCE_PRESET = previous.SOURCE_PRESET
PILOT_AUDIO_DIR = PROJECT_ROOT / "data/raw/audio" / DATASET_NAME
PILOT_MANIFEST_CSV = PROJECT_ROOT / "data/manifests" / f"{DATASET_NAME}.csv"
PILOT_MANIFEST_PARQUET = PILOT_MANIFEST_CSV.with_suffix(".parquet")
SAMPLE_RATE = previous.SAMPLE_RATE
MIDI_NOTE = previous.MIDI_NOTE
VELOCITY = previous.VELOCITY
NOTE_DURATION = previous.NOTE_DURATION
RENDER_DURATION = previous.RENDER_DURATION
PILOT_SAMPLE_COUNT = previous.PILOT_SAMPLE_COUNT
SAMPLING_SEED = previous.SAMPLING_SEED
PARAMS = deepcopy(previous.PARAMS)
PARAMS["filter_env_sustain"] = deepcopy(architecture_a.PARAMS["filter_env_sustain"])
FIXED_CONTROLS = deepcopy(previous.FIXED_CONTROLS)
del FIXED_CONTROLS["env_2_sustain"]
MODULATIONS = deepcopy(previous.MODULATIONS)
EXPECTED_CONTROL_TEXT = deepcopy(previous.EXPECTED_CONTROL_TEXT)
BASE_VALUES = dict(previous.BASE_VALUES, filter_env_sustain=.4)
