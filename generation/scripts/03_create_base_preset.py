from pathlib import Path

import vita


SAMPLE_RATE = 44_100

GENERATION_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = GENERATION_DIR / "presets" / "base_init.vital"


def require_control(controls, name: str):
    """Return a required Vital control or fail clearly."""
    if name not in controls:
        raise KeyError(f"Required Vital control was not found: {name}")

    return controls[name]


def set_raw(controls, name: str, value: float) -> None:
    require_control(controls, name).set(float(value))


def set_normalized(controls, name: str, value: float) -> None:
    require_control(controls, name).set_normalized(float(value))


def set_optional_raw(controls, name: str, value: float) -> None:
    """Set a control only if this Vita build exposes it."""
    if name in controls:
        controls[name].set(float(value))


def main() -> None:
    synth = vita.Synth()

    if hasattr(synth, "set_sample_rate"):
        synth.set_sample_rate(SAMPLE_RATE)

    # Vita's standard initialized preset.
    synth.load_init_preset()
    synth.clear_modulations()

    controls = synth.get_controls()

    # ── Sound sources ────────────────────────────────────────────────
    set_raw(controls, "osc_1_on", 1)
    set_raw(controls, "osc_2_on", 0)
    set_raw(controls, "osc_3_on", 0)
    set_optional_raw(controls, "sample_on", 0)

    # 0 = FILTER 1, verified by your inspection.
    set_raw(controls, "osc_1_destination", 0)

    # Keep pitch constant.
    set_raw(controls, "osc_1_transpose", 0)
    set_raw(controls, "osc_1_tune", 0)

    # Deterministic phase improves dataset reproducibility.
    set_raw(controls, "osc_1_random_phase", 0)

    # Start with one voice. The unison tests will override this.
    set_raw(controls, "osc_1_unison_voices", 1)
    set_normalized(controls, "osc_1_unison_detune", 0)

    # 50% displayed oscillator level.
    set_normalized(controls, "osc_1_level", 0.5)

    # ── Filter ───────────────────────────────────────────────────────
    set_raw(controls, "filter_1_on", 1)
    set_raw(controls, "filter_2_on", 0)

    # Verified categories:
    # model 0 = Analog
    # style 0 = 12dB
    set_raw(controls, "filter_1_model", 0)
    set_raw(controls, "filter_1_style", 0)

    set_raw(controls, "filter_1_mix", 1)
    set_raw(controls, "filter_1_keytrack", 0)

    # Around +24.8 displayed semitones.
    set_normalized(controls, "filter_1_cutoff", 0.60)
    set_normalized(controls, "filter_1_resonance", 0.20)
    set_normalized(controls, "filter_1_blend", 0.00)
    set_normalized(controls, "filter_1_drive", 0.00)

    # ── Amp envelope ─────────────────────────────────────────────────
    # From your calibration:
    # attack 0.10 ≈ 0.0032 sec
    # decay 0.30 ≈ 0.259 sec
    # release 0.30 ≈ 0.259 sec
    set_normalized(controls, "env_1_attack", 0.10)
    set_normalized(controls, "env_1_decay", 0.30)
    set_normalized(controls, "env_1_sustain", 0.80)
    set_normalized(controls, "env_1_release", 0.30)

    # ── Effects ──────────────────────────────────────────────────────
    effect_switches = [
        "chorus_on",
        "compressor_on",
        "delay_on",
        "distortion_on",
        "eq_on",
        "filter_fx_on",
        "flanger_on",
        "phaser_on",
        "reverb_on",
    ]

    for control_name in effect_switches:
        set_optional_raw(controls, control_name, 0)

    # Raw zero displayed as approximately one second in the
    # initial preset. Do not use set_normalized() on this control.
    set_optional_raw(controls, "reverb_decay_time", 0)

    set_optional_raw(controls, "polyphony", 1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        synth.to_json(),
        encoding="utf-8",
    )

    # Verify that the preset can be loaded again.
    verifier = vita.Synth()

    if not verifier.load_preset(str(OUTPUT_PATH)):
        raise RuntimeError("Saved preset could not be loaded again.")

    print("Base preset created successfully.")
    print(f"Saved to: {OUTPUT_PATH}")
    print(
        "Filter model:",
        synth.get_control_text("filter_1_model"),
    )
    print(
        "Filter style:",
        synth.get_control_text("filter_1_style"),
    )
    print(
        "Filter cutoff:",
        synth.get_control_text("filter_1_cutoff"),
    )
    print(
        "Attack:",
        synth.get_control_text("env_1_attack"),
    )
    print(
        "Release:",
        synth.get_control_text("env_1_release"),
    )


if __name__ == "__main__":
    main()