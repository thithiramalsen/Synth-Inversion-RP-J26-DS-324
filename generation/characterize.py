"""Numerical control checks for restricted_v2; these do not validate perception.

Run: python -m generation.characterize
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import soundfile as sf

from generation import restricted_config as profile
from generation.vital_setup import apply_parameters, create_synth

DEFAULT_REPORT = profile.PROJECT_ROOT / "generation/characterization/restricted_v2"
DEFAULT_AUDIO = profile.PROJECT_ROOT / "generation/test_renders/restricted_v2"


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(audio, dtype=np.float64) ** 2)))


def render(values: dict[str, float], overrides: dict[str, float] | None = None) -> np.ndarray:
    synth = create_synth(profile)
    apply_parameters(synth, profile, values)
    for name, raw_value in (overrides or {}).items():
        synth.get_controls()[name].set(raw_value)
    audio = np.asarray(synth.render(profile.MIDI_NOTE, profile.VELOCITY,
                                    profile.NOTE_DURATION, profile.RENDER_DURATION))
    if audio.shape != (2, int(profile.SAMPLE_RATE * profile.RENDER_DURATION)) or not np.isfinite(audio).all():
        raise ValueError("Invalid render shape or nonfinite audio")
    if np.max(np.abs(audio[0] - audio[1])) > 1e-7:
        raise ValueError("Stereo mismatch in declared mono domain")
    return audio[0].copy()


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def characterize(report_dir: Path = DEFAULT_REPORT, audio_dir: Path = DEFAULT_AUDIO) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    contexts = {
        "low_cutoff": dict(wave_frame=0.25, filter_cutoff=0.35),
        "middle_cutoff": dict(wave_frame=0.50, filter_cutoff=0.50),
        "high_cutoff": dict(wave_frame=0.80, filter_cutoff=0.75),
    }
    effects, renders, calibration = [], [], []
    synth = create_synth(profile)
    controls = synth.get_controls()
    for name, spec in profile.PARAMS.items():
        for label, value in [("low", spec["min"]), ("middle", (spec["min"] + spec["max"]) / 2), ("high", spec["max"])]:
            controls[spec["control"]].set_normalized(value)
            calibration.append(dict(parameter=name, point=label, requested_normalized=value,
                                    actual_normalized=controls[spec["control"]].get_normalized(),
                                    raw=controls[spec["control"]].value(),
                                    display=synth.get_control_text(spec["control"])))
    for context, overrides in contexts.items():
        base = dict(profile.BASE_VALUES, **overrides)
        base["filter_env_amount"] = profile.PARAMS["filter_env_amount"]["max"]
        for name, spec in profile.PARAMS.items():
            variants = []
            for label, value in [("low", spec["min"]), ("middle", (spec["min"] + spec["max"]) / 2), ("high", spec["max"])]:
                values = dict(base, **{name: value})
                audio = render(values)
                variants.append(audio)
                sample_id = f"{context}_{name}_{label}"
                path = audio_dir / f"{sample_id}.wav"
                sf.write(path, audio, profile.SAMPLE_RATE, subtype="PCM_16")
                level = rms(audio)
                dc = float(np.mean(audio, dtype=np.float64))
                renders.append(dict(sample_id=sample_id, context=context, varied_parameter=name,
                                    point=label, audio_path=path.relative_to(profile.PROJECT_ROOT).as_posix()
                                    if path.is_relative_to(profile.PROJECT_ROOT) else str(path),
                                    audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                    peak=float(np.max(np.abs(audio))), rms=level,
                                    dc_offset=dc, has_dc_warning=abs(dc) >= .005 or abs(dc) / max(level, 1e-12) >= .2,
                                    is_silent=level < .001, is_clipped=bool(np.max(np.abs(audio)) >= 1),
                                    **values))
            delta = rms(variants[2] - variants[0])
            relative = delta / max(rms(variants[0]), rms(variants[2]), 1e-12)
            effects.append(dict(context=context, parameter=name, low_high_difference_rms=delta,
                                relative_difference_rms=relative, numerically_active=relative > 1e-4))
        print(f"Characterized 12 controls in {context}", flush=True)

    baseline = dict(profile.BASE_VALUES)
    repeated_a, repeated_b = render(baseline), render(baseline)
    repeat_error = float(np.max(np.abs(repeated_a - repeated_b)))
    null_checks = []
    for name in ("filter_env_attack", "filter_env_decay", "filter_env_sustain"):
        zero = dict(baseline, filter_env_amount=.5)
        a = render(dict(zero, **{name: profile.PARAMS[name]["min"]}))
        b = render(dict(zero, **{name: profile.PARAMS[name]["max"]}))
        error = float(np.max(np.abs(a - b)))
        null_checks.append(dict(condition="zero_filter_envelope_depth", parameter=name,
                               maximum_absolute_difference=error, passed=error <= 1e-7))
    sustained = dict(baseline, filter_env_sustain=1.0)
    a = render(dict(sustained, filter_env_decay=profile.PARAMS["filter_env_decay"]["min"]))
    b = render(dict(sustained, filter_env_decay=profile.PARAMS["filter_env_decay"]["max"]))
    error = float(np.max(np.abs(a - b)))
    null_checks.append(dict(condition="filter_envelope_sustain_one", parameter="filter_env_decay",
                           maximum_absolute_difference=error, passed=error <= 1e-7))

    # Diagnostic overrides intentionally go outside candidate timing bounds to
    # create a constant envelope. Compare its depth against a static raw cutoff.
    constant = dict(baseline, filter_env_sustain=1., amp_sustain=1., filter_env_amount=.5625)
    reference = render(constant, {"env_2_attack": 0., "env_2_decay": 0.})
    steady = slice(int(.1 * profile.SAMPLE_RATE), int(1.4 * profile.SAMPLE_RATE))
    depth_errors = {}
    for semitones in (0, 8, 16, 24):
        static = render(dict(constant, filter_env_amount=.5), {
            "env_2_attack": 0., "env_2_decay": 0.,
            "filter_1_cutoff": 8 + 128 * constant["filter_cutoff"] + semitones,
        })
        depth_errors[semitones] = rms(reference[steady] - static[steady]) / max(rms(reference[steady]), 1e-12)
    depth_passed = min(depth_errors, key=depth_errors.get) == 16 and depth_errors[16] < .01
    active = {name: any(r["numerically_active"] for r in effects if r["parameter"] == name)
              for name in profile.PARAMS}
    summary = dict(
        dataset_name=profile.DATASET_NAME, schema_status=profile.SCHEMA_STATUS,
        purpose="Technical activity/reproducibility checks, NOT a human study or proof of perceptual coverage",
        base_preset_sha256=hashlib.sha256(profile.BASE_PRESET.read_bytes()).hexdigest(),
        versions={name: version(name) for name in ("vita", "numpy", "soundfile")},
        parameter_order=list(profile.PARAMS), parameters=profile.PARAMS,
        fixed_controls=profile.FIXED_CONTROLS, modulations=profile.MODULATIONS,
        sample_rate=profile.SAMPLE_RATE, midi_note=profile.MIDI_NOTE, velocity=profile.VELOCITY,
        note_duration_seconds=profile.NOTE_DURATION, render_duration_seconds=profile.RENDER_DURATION,
        contexts=contexts, base_values=profile.BASE_VALUES,
        effect_probe_filter_env_amount=profile.PARAMS["filter_env_amount"]["max"],
        sweep_render_count=len(renders), numerically_active_by_parameter=active,
        numerical_activity_threshold_relative_rms=1e-4,
        repeated_render_maximum_absolute_difference=repeat_error,
        negative_controls=null_checks,
        depth_check=dict(normalized=.5625, raw=.125, nominal_semitones=16,
                         relative_errors_by_static_semitone_offset=depth_errors, passed=depth_passed,
                         tolerance_relative_rms=.01, steady_window_seconds=[.1, 1.4]),
        silent_samples=sum(r["is_silent"] for r in renders),
        clipped_samples=sum(r["is_clipped"] for r in renders),
        dc_warning_samples=sum(r["has_dc_warning"] for r in renders),
    )
    summary["technical_checks_passed"] = (all(active.values()) and repeat_error <= 1e-7
                                           and all(r["passed"] for r in null_checks) and depth_passed
                                           and summary["silent_samples"] == summary["clipped_samples"] == 0)
    write_csv(report_dir / "control_calibration.csv", calibration)
    write_csv(report_dir / "control_effects.csv", effects)
    write_csv(report_dir / "render_manifest.csv", renders)
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO)
    args = parser.parse_args()
    result = characterize(args.report_dir.resolve(), args.audio_dir.resolve())
    print(json.dumps({k: result[k] for k in ("technical_checks_passed", "sweep_render_count", "silent_samples", "clipped_samples", "dc_warning_samples")}, indent=2))
    if not result["technical_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
