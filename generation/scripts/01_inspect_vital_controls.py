from pathlib import Path

import vita


OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "vital_controls.txt"
)

IMPORTANT_CONTROLS = [
    # Oscillators
    "osc_1_on",
    "osc_1_level",
    "osc_1_destination",
    "osc_1_wave_frame",
    "osc_1_transpose",
    "osc_1_tune",
    "osc_1_random_phase",
    "osc_1_unison_voices",
    "osc_1_unison_detune",
    "osc_2_on",
    "osc_3_on",

    # Filter
    "filter_1_on",
    "filter_1_model",
    "filter_1_style",
    "filter_1_cutoff",
    "filter_1_resonance",
    "filter_1_blend",
    "filter_1_drive",
    "filter_1_mix",
    "filter_1_keytrack",
    "filter_2_on",

    # Envelope
    "env_1_attack",
    "env_1_decay",
    "env_1_sustain",
    "env_1_release",

    # Effects
    "reverb_on",
    "reverb_dry_wet",
    "reverb_decay_time",
    "distortion_on",
    "distortion_drive",
    "distortion_mix",
]


def safe_call(function):
    try:
        return function()
    except Exception as error:
        return f"<error: {error}>"


def describe_control(synth, controls, name: str) -> list[str]:
    lines = [f"CONTROL: {name}"]

    if name not in controls:
        lines.append("STATUS: NOT FOUND")
        return lines

    control = controls[name]

    raw_value = safe_call(control.value)
    normalized = safe_call(control.get_normalized)
    display_text = safe_call(
        lambda: synth.get_control_text(name)
    )
    details = safe_call(
        lambda: synth.get_control_details(name)
    )

    lines.append(f"RAW VALUE: {raw_value}")
    lines.append(f"NORMALIZED VALUE: {normalized}")
    lines.append(f"DISPLAY TEXT: {display_text}")
    lines.append(f"DETAILS: {details}")

    if not isinstance(details, str) and hasattr(details, "options"):
        lines.append(f"OPTIONS: {list(details.options)}")

    return lines


def main() -> None:
    synth = vita.Synth()
    synth.load_init_preset()

    controls = synth.get_controls()
    all_names = sorted(controls.keys())

    lines = [
        "VITA CONTROL INSPECTION",
        f"TOTAL CONTROLS: {len(all_names)}",
        "",
        "=" * 80,
        "IMPORTANT CONTROLS",
        "=" * 80,
        "",
    ]

    for name in IMPORTANT_CONTROLS:
        lines.extend(
            describe_control(synth, controls, name)
        )
        lines.append("-" * 80)

    lines.extend(
        [
            "",
            "=" * 80,
            "ALL CONTROL NAMES",
            "=" * 80,
            "",
        ]
    )

    for index, name in enumerate(all_names):
        lines.append(f"{index:04d} | {name}")

    OUTPUT_PATH.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"Found {len(all_names)} controls.")
    print(f"Saved output to:\n{OUTPUT_PATH}")


if __name__ == "__main__":
    main()