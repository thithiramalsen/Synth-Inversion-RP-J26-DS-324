"""Inspect the pinned 13-control mappings and preset round trips; never render."""
import argparse
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path

from generation import bend_sustain_config as profile
from generation.vital_setup import create_synth, validate_synth


def nominal_value(name, raw):
    if name == "filter_cutoff":
        return {"base_hz_nominal": 440 * 2 ** ((raw - 69) / 12),
                "display_semitones_relative_to_midi_60": raw - 60}
    if name in ("amp_attack", "amp_decay", "amp_release", "filter_env_attack", "filter_env_decay"):
        return {"seconds_nominal": raw ** 4}
    if name == "filter_env_amount":
        return {"peak_cutoff_depth_semitones_nominal": 128 * raw}
    return {}


def audit():
    synth = create_synth(profile)
    restored = create_synth(profile)
    controls = synth.get_controls()
    details = {}
    for name, spec in profile.PARAMS.items():
        meta = synth.get_control_details(spec["control"])
        details[name] = {key: getattr(meta, key) for key in
                         ("min", "max", "display_multiply", "post_offset", "display_units", "is_discrete")}
        details[name].update(control=spec["control"], scale=str(meta.scale),
                             restricted_min=spec["min"], restricted_max=spec["max"], points=[])
        if meta.is_discrete:
            raise ValueError(f"Unexpected discrete control: {name}")
    checks = 0
    for index in range(17):
        fraction = index / 16
        expected = {}
        for name, spec in profile.PARAMS.items():
            normalized = spec["min"] + fraction * (spec["max"] - spec["min"])
            control = controls[spec["control"]]
            control.set_normalized(normalized)
            actual, raw = control.get_normalized(), control.value()
            if not math.isclose(actual, normalized, abs_tol=2e-6, rel_tol=0):
                raise ValueError(f"Normalized round trip failed: {name}")
            control.set(raw)
            if not math.isclose(control.get_normalized(), actual, abs_tol=2e-6, rel_tol=0):
                raise ValueError(f"Native round trip failed: {name}")
            display = synth.get_control_text(spec["control"])
            meta = details[name]
            # These 13 controls' wrapper normalized coordinates are linear in
            # native values, including the envelope's pre-quartic native value.
            predicted_raw = meta["min"] + normalized * (meta["max"] - meta["min"])
            if not math.isclose(raw, predicted_raw, abs_tol=2e-5, rel_tol=0):
                raise ValueError(f"Unexpected native mapping: {name}")
            scaled = raw ** 4 if meta["scale"] == "ValueScale.Quartic" else raw
            predicted_display = (scaled + meta["post_offset"]) * meta["display_multiply"]
            numeric_display = float(display.replace(meta["display_units"], "") if meta["display_units"] else display)
            if not math.isclose(numeric_display, predicted_display, abs_tol=2e-5, rel_tol=0):
                raise ValueError(f"Unexpected display mapping: {name}")
            expected[name] = (actual, raw, display)
            meta["points"].append(dict(requested_normalized=normalized, actual_normalized=actual,
                                       native=raw, display=display, **nominal_value(name, raw)))
        if not restored.load_json(synth.to_json()):
            raise ValueError("Preset serialization failed")
        validate_synth(restored, profile)
        for name, spec in profile.PARAMS.items():
            control = restored.get_controls()[spec["control"]]
            normalized, raw, display = expected[name]
            if (not math.isclose(control.get_normalized(), normalized, abs_tol=2e-6, rel_tol=0)
                    or not math.isclose(control.value(), raw, abs_tol=2e-5, rel_tol=0)
                    or restored.get_control_text(spec["control"]) != display):
                raise ValueError(f"Preset round trip failed: {name}")
            checks += 1
    return dict(profile=profile.DATASET_NAME, vita_version=version("vita"),
                preset_sha256=hashlib.sha256(profile.BASE_PRESET.read_bytes()).hexdigest(),
                checked_parameter_points=checks, preset_round_trips=17,
                audio_rendered=False, mappings=details,
                limits="Tests wrapper/state mappings, not measured acoustic response. Nominal cutoff is before envelope modulation; depth is nominal at full unipolar envelope output.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output JSON; existing reports are preserved")
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(f"PASS: {result['checked_parameter_points']} parameter points and 17 preset round trips. No rendering.")
    print(args.output)
