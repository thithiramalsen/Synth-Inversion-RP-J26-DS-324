"""Shared profile selection and validation for generation and characterization."""

from __future__ import annotations

import importlib
import hashlib
import json
import math
from pathlib import Path

PROFILES = {"pilot_v1": "generation.params_config", "restricted_v2": "generation.restricted_config"}


def load_profile(name: str):
    return importlib.import_module(PROFILES[name])


def set_sample_rate(synth, sample_rate: int) -> None:
    if hasattr(synth, "set_sample_rate"):
        synth.set_sample_rate(sample_rate)
    elif sample_rate != 44_100:
        raise ValueError("This Vita build renders at 44100 Hz and cannot change sample rate")


def set_control(controls, name: str, mode: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite control value: {name}")
    if mode == "normalized":
        if not 0 <= value <= 1:
            raise ValueError(f"Normalized value outside [0, 1]: {name}={value}")
        controls[name].set_normalized(float(value))
    elif mode == "raw":
        controls[name].set(float(value))
    else:
        raise ValueError(f"Unknown control mode: {mode}")


def validate_synth(synth, profile) -> None:
    controls = synth.get_controls()
    for name, (mode, expected) in profile.FIXED_CONTROLS.items():
        actual = controls[name].get_normalized() if mode == "normalized" else controls[name].value()
        if not math.isclose(actual, expected, abs_tol=2e-6):
            raise ValueError(f"Fixed control mismatch: {name}: {actual} != {expected}")
    settings = json.loads(synth.to_json())["settings"]
    actual_routes = [(i + 1, m.get("source"), m.get("destination"))
                     for i, m in enumerate(settings["modulations"])
                     if m.get("source") or m.get("destination")]
    expected_routes = [(m["slot"], m["source"], m["destination"]) for m in profile.MODULATIONS]
    if actual_routes != expected_routes:
        raise ValueError(f"Modulation routing mismatch: {actual_routes} != {expected_routes}")
    for name, spec in profile.PARAMS.items():
        if spec["control"] not in controls or spec["control"] in profile.FIXED_CONTROLS:
            raise ValueError(f"Missing or simultaneously fixed parameter: {name}")
        if spec["mode"] != "normalized" or not 0 <= spec["min"] < spec["max"] <= 1:
            raise ValueError(f"Invalid normalized bounds: {name}")


def create_synth(profile):
    import vita
    synth = vita.Synth()
    set_sample_rate(synth, profile.SAMPLE_RATE)
    if not synth.load_preset(str(profile.BASE_PRESET)):
        raise RuntimeError(f"Could not load preset: {profile.BASE_PRESET}")
    validate_synth(synth, profile)
    return synth


def apply_parameters(synth, profile, values: dict[str, float]) -> None:
    controls = synth.get_controls()
    for name, value in values.items():
        spec = profile.PARAMS[name]
        if not spec["min"] - 1e-8 <= value <= spec["max"] + 1e-8:
            raise ValueError(f"{name}={value} is outside the candidate domain")
        set_control(controls, spec["control"], spec["mode"], value)


def build_restricted_preset() -> Path:
    import vita
    profile = load_profile("restricted_v2")
    synth = vita.Synth()
    set_sample_rate(synth, profile.SAMPLE_RATE)
    if not profile.SOURCE_PRESET.is_file() or not synth.load_preset(str(profile.SOURCE_PRESET)):
        raise FileNotFoundError(f"Missing/unloadable Basic Shapes source: {profile.SOURCE_PRESET}")
    synth.clear_modulations()
    for route in profile.MODULATIONS:
        if not synth.connect_modulation(route["source"], route["destination"]):
            raise RuntimeError(f"Cannot connect modulation: {route}")
    controls = synth.get_controls()
    for name, (mode, value) in profile.FIXED_CONTROLS.items():
        set_control(controls, name, mode, value)
    apply_parameters(synth, profile, profile.BASE_VALUES)
    validate_synth(synth, profile)
    payload = synth.to_json()
    verifier = vita.Synth()
    if not verifier.load_json(payload):
        raise RuntimeError("New preset failed serialization round trip")
    validate_synth(verifier, profile)
    path = profile.BASE_PRESET
    config_path = profile.PILOT_MANIFEST_CSV.with_name(f"{profile.DATASET_NAME}_config.json")
    if config_path.exists():
        saved_hash = json.loads(config_path.read_text(encoding="utf-8")).get("base_preset_sha256")
        if saved_hash != hashlib.sha256(payload.encode("utf-8")).hexdigest():
            raise FileExistsError("Preset already belongs to a dataset. Create a new dataset version to change it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.encode("utf-8"))
    return path
