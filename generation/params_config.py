from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BASE_PRESET = (
    PROJECT_ROOT
    / "generation"
    / "presets"
    / "base_basic_shapes_RP.vital"
)

PILOT_AUDIO_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "audio"
    / "pilot_v1"
)

PILOT_MANIFEST_CSV = (
    PROJECT_ROOT
    / "data"
    / "manifests"
    / "pilot_v1.csv"
)

PILOT_MANIFEST_PARQUET = (
    PROJECT_ROOT
    / "data"
    / "manifests"
    / "pilot_v1.parquet"
)


# ── Rendering configuration ─────────────────────────────────────────

SAMPLE_RATE = 44_100
MIDI_NOTE = 60
VELOCITY = 0.80
NOTE_DURATION = 1.50
RENDER_DURATION = 3.00

PILOT_SAMPLE_COUNT = 100
SAMPLING_SEED = 20260803


# ── Dataset Version 1 parameters ────────────────────────────────────
#
# All ranges use Vita's normalized 0–1 parameter space.
# These are intentionally conservative pilot ranges.
#
# They can be expanded after checking silence, clipping,
# duplicate sounds and perceptual coverage.

PARAMS = {
    "wave_frame": {
        "control": "osc_1_wave_frame",
        "mode": "normalized",
        "min": 0.00,
        "max": 1.00,
        "description": (
            "Position within the fixed Basic Shapes wavetable."
        ),
    },

    "filter_cutoff": {
        "control": "filter_1_cutoff",
        "mode": "normalized",
        "min": 0.30,
        "max": 0.85,
        "description": (
            "Analog 12 dB filter cutoff. Extremely low values "
            "are excluded to reduce near-silent samples."
        ),
    },

    "filter_resonance": {
        "control": "filter_1_resonance",
        "mode": "normalized",
        "min": 0.00,
        "max": 0.80,
        "description": "Analog filter resonance.",
    },

    "filter_drive": {
        "control": "filter_1_drive",
        "mode": "normalized",
        "min": 0.00,
        "max": 0.75,
        "description": "Internal drive of Filter 1.",
    },

    "amp_attack": {
        "control": "env_1_attack",
        "mode": "normalized",
        "min": 0.05,
        "max": 0.45,
        "description": (
            "Amplitude-envelope attack. The upper extreme is "
            "restricted to fit the three-second render."
        ),
    },

    "amp_decay": {
        "control": "env_1_decay",
        "mode": "normalized",
        "min": 0.15,
        "max": 0.50,
        "description": "Amplitude-envelope decay.",
    },

    "amp_sustain": {
        "control": "env_1_sustain",
        "mode": "normalized",
        "min": 0.20,
        "max": 1.00,
        "description": (
            "Amplitude-envelope sustain. Very low sustain "
            "values are excluded from the first pilot."
        ),
    },

    "amp_release": {
        "control": "env_1_release",
        "mode": "normalized",
        "min": 0.10,
        "max": 0.45,
        "description": (
            "Amplitude-envelope release, restricted so most "
            "of the tail fits inside the render."
        ),
    },
}


# ── Controls locked across Dataset Version 1 ────────────────────────

FIXED_CONTROLS = {
    # Sources
    "osc_1_on": ("raw", 1.0),
    "osc_2_on": ("raw", 0.0),
    "osc_3_on": ("raw", 0.0),
    "sample_on": ("raw", 0.0),

    # Routing and pitch
    "osc_1_destination": ("raw", 0.0),
    "osc_1_transpose": ("raw", 0.0),
    "osc_1_tune": ("raw", 0.0),
    "osc_1_random_phase": ("raw", 0.0),
    "osc_1_level": ("normalized", 0.50),

    # Unison
    "osc_1_unison_voices": ("raw", 1.0),
    "osc_1_unison_detune": ("normalized", 0.0),

    # Filter
    "filter_1_on": ("raw", 1.0),
    "filter_2_on": ("raw", 0.0),
    "filter_1_model": ("raw", 0.0),
    "filter_1_style": ("raw", 0.0),
    "filter_1_mix": ("raw", 1.0),
    "filter_1_keytrack": ("raw", 0.0),
    "filter_1_blend": ("normalized", 0.0),

    # Effects
    "chorus_on": ("raw", 0.0),
    "compressor_on": ("raw", 0.0),
    "delay_on": ("raw", 0.0),
    "distortion_on": ("raw", 0.0),
    "eq_on": ("raw", 0.0),
    "filter_fx_on": ("raw", 0.0),
    "flanger_on": ("raw", 0.0),
    "phaser_on": ("raw", 0.0),
    "reverb_on": ("raw", 0.0),

    # Monophonic rendering
    "polyphony": ("raw", 1.0),
}