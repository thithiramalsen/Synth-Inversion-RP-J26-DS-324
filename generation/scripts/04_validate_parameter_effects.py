from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

import numpy as np
import vita
from scipy.io import wavfile


SAMPLE_RATE = 44_100
MIDI_NOTE = 60
VELOCITY = 0.8
NOTE_DURATION = 1.5
RENDER_DURATION = 3.0

GENERATION_DIR = Path(__file__).resolve().parents[1]
BASE_PRESET = (
    GENERATION_DIR
    / "presets"
    / "base_basic_shapes_RP.vital"
)
OUTPUT_DIR = GENERATION_DIR / "test_renders"
SUMMARY_PATH = OUTPUT_DIR / "validation_summary.csv"

SetMode = Literal["raw", "normalized"]
ControlChange = tuple[str, SetMode, float]


# Every group contains low, middle and high examples.
TEST_GROUPS: dict[str, list[tuple[str, list[ControlChange]]]] = {
    "wave_frame": [
        ("low", [("osc_1_wave_frame", "normalized", 0.0)]),
        ("middle", [("osc_1_wave_frame", "normalized", 0.5)]),
        ("high", [("osc_1_wave_frame", "normalized", 1.0)]),
    ],

    # Detune requires multiple oscillator voices.
    "unison_detune": [
        (
            "narrow",
            [
                ("osc_1_unison_voices", "raw", 4),
                ("osc_1_unison_detune", "normalized", 0.0),
            ],
        ),
        (
            "medium",
            [
                ("osc_1_unison_voices", "raw", 4),
                ("osc_1_unison_detune", "normalized", 0.35),
            ],
        ),
        (
            "wide",
            [
                ("osc_1_unison_voices", "raw", 4),
                ("osc_1_unison_detune", "normalized", 0.80),
            ],
        ),
    ],

    "filter_cutoff": [
        ("low", [("filter_1_cutoff", "normalized", 0.20)]),
        ("middle", [("filter_1_cutoff", "normalized", 0.50)]),
        ("high", [("filter_1_cutoff", "normalized", 0.80)]),
    ],

    "filter_resonance": [
        ("low", [("filter_1_resonance", "normalized", 0.0)]),
        ("middle", [("filter_1_resonance", "normalized", 0.50)]),
        ("high", [("filter_1_resonance", "normalized", 0.90)]),
    ],

    "filter_blend": [
        ("position_0", [("filter_1_blend", "normalized", 0.0)]),
        ("position_1", [("filter_1_blend", "normalized", 0.5)]),
        ("position_2", [("filter_1_blend", "normalized", 1.0)]),
    ],

    "filter_drive": [
        ("clean", [("filter_1_drive", "normalized", 0.0)]),
        ("medium", [("filter_1_drive", "normalized", 0.40)]),
        ("high", [("filter_1_drive", "normalized", 0.80)]),
    ],

    "amp_attack": [
        ("fast", [("env_1_attack", "normalized", 0.10)]),
        ("medium", [("env_1_attack", "normalized", 0.30)]),
        ("slow", [("env_1_attack", "normalized", 0.50)]),
    ],

    "amp_decay": [
        ("fast", [("env_1_decay", "normalized", 0.15)]),
        ("medium", [("env_1_decay", "normalized", 0.30)]),
        ("slow", [("env_1_decay", "normalized", 0.50)]),
    ],

    "amp_sustain": [
        ("low", [("env_1_sustain", "normalized", 0.10)]),
        ("middle", [("env_1_sustain", "normalized", 0.50)]),
        ("high", [("env_1_sustain", "normalized", 1.00)]),
    ],

    "amp_release": [
        ("fast", [("env_1_release", "normalized", 0.10)]),
        ("medium", [("env_1_release", "normalized", 0.30)]),
        ("slow", [("env_1_release", "normalized", 0.50)]),
    ],

    "reverb_mix": [
        (
            "dry",
            [
                ("reverb_on", "raw", 1),
                ("reverb_decay_time", "raw", 0),
                ("reverb_dry_wet", "normalized", 0.0),
            ],
        ),
        (
            "medium",
            [
                ("reverb_on", "raw", 1),
                ("reverb_decay_time", "raw", 0),
                ("reverb_dry_wet", "normalized", 0.30),
            ],
        ),
        (
            "wet",
            [
                ("reverb_on", "raw", 1),
                ("reverb_decay_time", "raw", 0),
                ("reverb_dry_wet", "normalized", 0.75),
            ],
        ),
    ],

    "distortion_drive": [
        (
            "clean",
            [
                ("distortion_on", "raw", 1),
                ("distortion_mix", "raw", 1),
                ("distortion_drive", "normalized", 0.50),
            ],
        ),
        (
            "medium",
            [
                ("distortion_on", "raw", 1),
                ("distortion_mix", "raw", 1),
                ("distortion_drive", "normalized", 0.75),
            ],
        ),
        (
            "high",
            [
                ("distortion_on", "raw", 1),
                ("distortion_mix", "raw", 1),
                ("distortion_drive", "normalized", 1.00),
            ],
        ),
    ],

        "wave_frame_raw": [
        (
            "low",
            [
                ("filter_1_on", "raw", 0),
                ("osc_1_wave_frame", "normalized", 0.0),
            ],
        ),
        (
            "middle",
            [
                ("filter_1_on", "raw", 0),
                ("osc_1_wave_frame", "normalized", 0.5),
            ],
        ),
        (
            "high",
            [
                ("filter_1_on", "raw", 0),
             ("osc_1_wave_frame", "normalized", 1.0),
            ],
        ),
    ],
}


def load_base_synth() -> vita.Synth:
    synth = vita.Synth()

    if hasattr(synth, "set_sample_rate"):
        synth.set_sample_rate(SAMPLE_RATE)

    if not synth.load_preset(str(BASE_PRESET)):
        raise RuntimeError(f"Could not load preset: {BASE_PRESET}")

    return synth


def apply_changes(
    synth: vita.Synth,
    changes: list[ControlChange],
) -> list[str]:
    controls = synth.get_controls()
    display_values: list[str] = []

    for name, mode, value in changes:
        if name not in controls:
            raise KeyError(f"Control not found: {name}")

        control = controls[name]

        if mode == "normalized":
            control.set_normalized(value)
        elif mode == "raw":
            control.set(value)
        else:
            raise ValueError(f"Unknown setting mode: {mode}")

        display_values.append(
            f"{name}={synth.get_control_text(name)}"
        )

    return display_values


def render_audio(synth: vita.Synth) -> np.ndarray:
    audio = synth.render(
        MIDI_NOTE,
        VELOCITY,
        NOTE_DURATION,
        RENDER_DURATION,
    )

    audio = np.asarray(audio, dtype=np.float32)

    if audio.ndim != 2 or audio.shape[0] != 2:
        raise ValueError(
            f"Expected stereo audio shaped (2, samples), got {audio.shape}"
        )

    if not np.all(np.isfinite(audio)):
        raise ValueError("Rendered audio contains NaN or infinity.")

    return audio


def rms(audio: np.ndarray) -> float:
    return float(
        np.sqrt(np.mean(np.square(audio.astype(np.float64))))
    )


def main() -> None:
    if not BASE_PRESET.exists():
        raise FileNotFoundError(
            "Run 03_create_base_preset.py first. "
            f"Missing: {BASE_PRESET}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, object]] = []

    for group_name, variants in TEST_GROUPS.items():
        group_dir = OUTPUT_DIR / group_name
        group_dir.mkdir(parents=True, exist_ok=True)

        reference_audio: np.ndarray | None = None

        print(f"\nTesting: {group_name}")

        for variant_name, changes in variants:
            synth = load_base_synth()
            display_values = apply_changes(synth, changes)
            audio = render_audio(synth)

            if reference_audio is None:
                reference_audio = audio.copy()

            difference = audio - reference_audio
            difference_rms = rms(difference)

            output_path = group_dir / f"{variant_name}.wav"

            wavfile.write(
                output_path,
                SAMPLE_RATE,
                audio.T.astype(np.float32),
            )

            peak = float(np.max(np.abs(audio)))
            audio_rms = rms(audio)

            summary_rows.append(
                {
                    "group": group_name,
                    "variant": variant_name,
                    "file": str(output_path),
                    "peak": peak,
                    "audio_rms": audio_rms,
                    "difference_rms_from_first": difference_rms,
                    "display_values": "; ".join(display_values),
                }
            )

            print(
                f"  {variant_name:<12} "
                f"peak={peak:.6f} "
                f"rms={audio_rms:.6f} "
                f"diff={difference_rms:.6f}"
            )
            print(f"    {'; '.join(display_values)}")

    with SUMMARY_PATH.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "group",
                "variant",
                "file",
                "peak",
                "audio_rms",
                "difference_rms_from_first",
                "display_values",
            ],
        )

        writer.writeheader()
        writer.writerows(summary_rows)

    print("\nValidation finished.")
    print(f"Audio directory: {OUTPUT_DIR}")
    print(f"Summary: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()