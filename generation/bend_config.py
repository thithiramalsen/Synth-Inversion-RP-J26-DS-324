"""Selected one-oscillator Bend architecture; audio policy/ranges still provisional.

restricted_v2 remains the immutable architecture-A reference. This new version
replaces variable ENV2 sustain with Bend amount; no old audio is relabelled.
"""

from copy import deepcopy

from generation import restricted_config as architecture_a

PROJECT_ROOT = architecture_a.PROJECT_ROOT
DATASET_NAME = "restricted_bend_v3"
SCHEMA_STATUS = "selected_architecture_pending_audio_policy"
BASE_PRESET = PROJECT_ROOT / "generation/presets/base_restricted_bend_v3.vital"
SOURCE_PRESET = architecture_a.SOURCE_PRESET
PILOT_AUDIO_DIR = PROJECT_ROOT / "data/raw/audio" / DATASET_NAME
PILOT_MANIFEST_CSV = PROJECT_ROOT / "data/manifests" / f"{DATASET_NAME}.csv"
PILOT_MANIFEST_PARQUET = PILOT_MANIFEST_CSV.with_suffix(".parquet")

SAMPLE_RATE = architecture_a.SAMPLE_RATE
MIDI_NOTE = architecture_a.MIDI_NOTE
VELOCITY = architecture_a.VELOCITY
NOTE_DURATION = architecture_a.NOTE_DURATION
RENDER_DURATION = architecture_a.RENDER_DURATION
PILOT_SAMPLE_COUNT = 1024
SAMPLING_SEED = architecture_a.SAMPLING_SEED

PARAMS = {"wave_frame": deepcopy(architecture_a.PARAMS["wave_frame"]),
          "bend_amount": {
              "control": "osc_1_distortion_amount", "mode": "normalized", "min": .25, "max": .75,
              "description": "Oscillator 1 Bend, fixed mode/phase. Normalized .5 is neutral. Provisional .25-.75 interval from the main A/B comparison; DC policy unresolved.",
          }}
PARAMS.update({name: deepcopy(spec) for name, spec in architecture_a.PARAMS.items()
               if name not in ("wave_frame", "filter_env_sustain")})

MODULATIONS = deepcopy(architecture_a.MODULATIONS)
FIXED_CONTROLS = deepcopy(architecture_a.FIXED_CONTROLS)
FIXED_CONTROLS.update({
    "env_2_sustain": ("raw", 0.),
    "osc_1_distortion_type": ("raw", 4.),  # Bend in the inspected Vita 0.0.5 build.
    "osc_1_distortion_phase": ("raw", .5),
    "osc_1_distortion_spread": ("raw", 0.),
    "osc_1_spectral_morph_type": ("raw", 0.),
    "osc_1_spectral_morph_amount": ("raw", .5),
    "osc_1_spectral_morph_spread": ("raw", 0.),
})
EXPECTED_CONTROL_TEXT = {"osc_1_distortion_type": "Bend", "osc_1_spectral_morph_type": "None"}
BASE_VALUES = {name: (.5 if name == "bend_amount" else architecture_a.BASE_VALUES[name]) for name in PARAMS}
