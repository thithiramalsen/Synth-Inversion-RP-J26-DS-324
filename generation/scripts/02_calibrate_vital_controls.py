from pathlib import Path

import vita


OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "vital_control_calibration.txt"
)

# Controls that may become dataset parameters.
CONTROL_NAMES = [
    # Oscillator
    "osc_1_level",
    "osc_1_wave_frame",
    "osc_1_unison_voices",
    "osc_1_unison_detune",

    # Filter
    "filter_1_cutoff",
    "filter_1_resonance",
    "filter_1_blend",
    "filter_1_drive",

    # Amplitude envelope
    "env_1_attack",
    "env_1_decay",
    "env_1_sustain",
    "env_1_release",

    # Reverb
    "reverb_dry_wet",
    "reverb_decay_time",

    # Distortion
    "distortion_drive",
    "distortion_mix",
]

# Extra points near zero are important because envelope controls
# use nonlinear scaling.
NORMALIZED_POSITIONS = [
    0.00,
    0.01,
    0.02,
    0.05,
    0.10,
    0.15,
    0.20,
    0.25,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    1.00,
]


def get_display_text(synth, name: str) -> str:
    try:
        return str(synth.get_control_text(name))
    except Exception as error:
        return f"<display error: {error}>"


def calibrate_control(name: str) -> list[str]:
    # Use a fresh synth for every control so one calibration
    # cannot affect another.
    synth = vita.Synth()
    synth.load_init_preset()

    controls = synth.get_controls()

    lines = [
        "=" * 90,
        f"CONTROL: {name}",
        "=" * 90,
    ]

    if name not in controls:
        lines.append("STATUS: NOT FOUND")
        lines.append("")
        return lines

    control = controls[name]

    lines.append(
        "REQUESTED NORMALIZED | ACTUAL NORMALIZED | "
        "RAW INTERNAL VALUE | DISPLAYED VALUE"
    )
    lines.append("-" * 90)

    for requested_position in NORMALIZED_POSITIONS:
        try:
            control.set_normalized(requested_position)

            actual_normalized = control.get_normalized()
            raw_value = control.value()
            display_text = get_display_text(synth, name)

            lines.append(
                f"{requested_position:>20.4f} | "
                f"{actual_normalized:>17.8f} | "
                f"{raw_value:>18.8f} | "
                f"{display_text}"
            )

        except Exception as error:
            lines.append(
                f"{requested_position:>20.4f} | "
                f"<error: {error}>"
            )

    lines.append("")
    return lines


def main() -> None:
    output_lines = [
        "VITAL CONTROL CALIBRATION",
        "",
        "This file maps normalized values to Vital's raw internal",
        "values and the values shown in Vital's interface.",
        "",
    ]

    for control_name in CONTROL_NAMES:
        output_lines.extend(
            calibrate_control(control_name)
        )

    OUTPUT_PATH.write_text(
        "\n".join(output_lines),
        encoding="utf-8",
    )

    print("Calibration complete.")
    print(f"Saved output to:\n{OUTPUT_PATH}")


if __name__ == "__main__":
    main()