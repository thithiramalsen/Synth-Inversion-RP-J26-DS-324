# generation/params_config.py
# Parameter definitions grounded in Surge XT Manual (2026)
# Oscillator type locked to: Classic
# All ranges verified against manual technical reference

PARAMS = {
    # ── Oscillator (Classic type, Osc 1 only) ──────────────────────────
    "osc_shape": {
        "type": "continuous",
        "min": -100.0, "max": 100.0,
        "surge_path": "osc1_shape",
        "note": "Morphs waveform character in Classic osc. -100=saw-like, +100=alt wave"
    },
    "osc_pulse_width": {
        "type": "continuous",
        "min": -100.0, "max": 100.0,
        "surge_path": "osc1_pw",
        "note": "Pulse width. Manual range: -100 to +100%"
    },
    "osc_unison_detune": {
        "type": "continuous",
        "min": 0.0, "max": 100.0,
        "surge_path": "osc1_unison_detune",
        "note": "Manual: 0..100 cents. Creates unison thickness."
    },
    "osc_pitch": {
        "type": "continuous",
        "min": -12.0, "max": 12.0,
        "surge_path": "osc1_pitch",
        "note": "Semitone offset from played note"
    },

    # ── Filter ─────────────────────────────────────────────────────────
    "filter_type": {
        "type": "categorical",
        "values": [0, 1, 2, 3],
        "labels": ["LP12", "LP24", "HP12", "BP12"],
        "surge_path": "filter1_type",
        "note": "From manual filter type list. 4 most perceptually distinct types."
    },
    "filter_cutoff": {
        "type": "continuous",
        "min": 80.0, "max": 8000.0,
        "surge_path": "filter1_cutoff",
        "note": "Manual max range: 13.75-25087.71 Hz. We restrict to 80-8000 Hz."
    },
    "filter_resonance": {
        "type": "continuous",
        "min": 0.0, "max": 1.0,
        "surge_path": "filter1_resonance",
        "note": "Normalised from manual 0-100% range"
    },

    # ── Amplitude Envelope (AEG) ───────────────────────────────────────
    "amp_attack": {
        "type": "continuous",
        "min": 0.001, "max": 2.0,
        "surge_path": "aeg_attack",
        "note": "Attack time in seconds. Manual confirms ADSR structure."
    },
    "amp_decay": {
        "type": "continuous",
        "min": 0.01, "max": 2.0,
        "surge_path": "aeg_decay",
        "note": "Decay time in seconds"
    },
    "amp_sustain": {
        "type": "continuous",
        "min": 0.0, "max": 1.0,
        "surge_path": "aeg_sustain",
        "note": "Sustain level, normalised"
    },
    "amp_release": {
        "type": "continuous",
        "min": 0.01, "max": 4.0,
        "surge_path": "aeg_release",
        "note": "Release time in seconds"
    },

    # ── Effects (FX unit Mix parameters) ──────────────────────────────
    "fx_reverb_mix": {
        "type": "continuous",
        "min": 0.0, "max": 1.0,
        "surge_path": "fx1_mix",
        "note": "Reverb 2 Mix. Manual: 0-100%. Load Reverb 2 into FX slot 1."
    },
    "fx_distortion_drive": {
        "type": "continuous",
        "min": 0.0, "max": 1.0,
        "surge_path": "fx2_drive",
        "note": "Distortion Drive normalised. Manual: -24 to +24 dB. Load Distortion into FX slot 2."
    },
}

# Convenience groupings used by all components
CONTINUOUS_PARAMS = [k for k, v in PARAMS.items() if v["type"] == "continuous"]
CATEGORICAL_PARAMS = [k for k, v in PARAMS.items() if v["type"] == "categorical"]
PARAM_NAMES = list(PARAMS.keys())
N_PARAMS = len(PARAMS)  # 13

# For C2 model output sizing
N_CONTINUOUS = len(CONTINUOUS_PARAMS)   # 12
N_CATEGORICAL = len(CATEGORICAL_PARAMS) # 1