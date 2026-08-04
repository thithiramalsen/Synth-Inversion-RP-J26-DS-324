from __future__ import annotations

import argparse
from email.mime import audio
import hashlib
import json
import math
import shutil
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import soundfile as sf
import vita
from scipy.stats import qmc


# Allow the script to import generation.params_config when executed
# directly from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from generation.params_config import (  # noqa: E402
    BASE_PRESET,
    FIXED_CONTROLS,
    MIDI_NOTE,
    NOTE_DURATION,
    PARAMS,
    PILOT_AUDIO_DIR,
    PILOT_MANIFEST_CSV,
    PILOT_MANIFEST_PARQUET,
    PILOT_SAMPLE_COUNT,
    RENDER_DURATION,
    SAMPLE_RATE,
    SAMPLING_SEED,
    VELOCITY,
)


SILENCE_THRESHOLD_DBFS = -60.0
CLIPPING_THRESHOLD = 1.0
DC_OFFSET_WARNING_THRESHOLD = 0.005
DC_TO_RMS_WARNING_THRESHOLD = 0.20
CHECKPOINT_INTERVAL = 10

CONFIG_PATH = PILOT_MANIFEST_CSV.parent / "pilot_v1_config.json"
SUMMARY_PATH = PILOT_MANIFEST_CSV.parent / "pilot_v1_summary.json"
REVIEW_LIST_PATH = PILOT_MANIFEST_CSV.parent / "pilot_v1_review_samples.txt"


# Sample rate helper function for Vita synths that support it. Some versions of Vita do not have this method.
def create_synth() -> vita.Synth:
    """Create a Vita synth and set the sample rate when supported."""
    synth = vita.Synth()

    if hasattr(synth, "set_sample_rate"):
        synth.set_sample_rate(SAMPLE_RATE)

    return synth


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the Vital Dataset V1 pilot."
    )

    parser.add_argument(
        "--count",
        type=int,
        default=PILOT_SAMPLE_COUNT,
        help=f"Number of sounds to generate. Default: {PILOT_SAMPLE_COUNT}",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete and replace an existing pilot dataset.",
    )

    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def dbfs(value: float) -> float:
    if value <= 0:
        return -120.0

    return float(20.0 * np.log10(value))


def rms(audio: np.ndarray) -> float:
    audio_64 = audio.astype(np.float64)

    return float(
        np.sqrt(
            np.mean(
                np.square(audio_64)
            )
        )
    )


def create_sobol_samples(
    sample_count: int,
    dimensions: int,
    seed: int,
) -> np.ndarray:
    """
    Generate a balanced Sobol sequence.

    random_base2 requires a power-of-two sample count, so the script
    creates the next power of two and then keeps only the requested rows.
    """
    if sample_count <= 0:
        raise ValueError("Sample count must be greater than zero.")

    if dimensions <= 0:
        raise ValueError("At least one parameter is required.")

    power = math.ceil(math.log2(sample_count))

    sampler = qmc.Sobol(
    d=dimensions,
    scramble=True,
    rng=np.random.default_rng(seed),
    )

    samples = sampler.random_base2(m=power)

    return samples[:sample_count]


def prepare_output_directories(overwrite: bool) -> None:
    PILOT_MANIFEST_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if PILOT_AUDIO_DIR.exists():
        existing_wavs = list(
            PILOT_AUDIO_DIR.glob("*.wav")
        )

        if existing_wavs and not overwrite:
            raise FileExistsError(
                f"{PILOT_AUDIO_DIR} already contains "
                f"{len(existing_wavs)} WAV files.\n"
                "Run with --overwrite to replace them."
            )

        if overwrite:
            shutil.rmtree(PILOT_AUDIO_DIR)

    PILOT_AUDIO_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if overwrite:
        for file_path in [
            PILOT_MANIFEST_CSV,
            PILOT_MANIFEST_PARQUET,
            CONFIG_PATH,
            SUMMARY_PATH,
            REVIEW_LIST_PATH,
        ]:
            if file_path.exists():
                file_path.unlink()


def validate_configuration() -> None:
    if not BASE_PRESET.exists():
        raise FileNotFoundError(
            f"Base preset was not found:\n{BASE_PRESET}"
        )

    if not PARAMS:
        raise ValueError("PARAMS is empty.")

    synth = create_synth()

    if not synth.load_preset(str(BASE_PRESET)):
        raise RuntimeError(
            f"Vita could not load:\n{BASE_PRESET}"
        )

    controls = synth.get_controls()

    missing_controls: list[str] = []

    for parameter in PARAMS.values():
        control_name = parameter["control"]

        if control_name not in controls:
            missing_controls.append(control_name)

    for control_name in FIXED_CONTROLS:
        if control_name not in controls:
            missing_controls.append(control_name)

    if missing_controls:
        missing_text = "\n".join(
            sorted(set(missing_controls))
        )

        raise KeyError(
            "The following controls are missing from Vita:\n"
            f"{missing_text}"
        )


def set_control(
    controls: Any,
    name: str,
    mode: str,
    value: float,
) -> None:
    if name not in controls:
        raise KeyError(f"Vital control not found: {name}")

    if mode == "normalized":
        controls[name].set_normalized(float(value))
    elif mode == "raw":
        controls[name].set(float(value))
    else:
        raise ValueError(
            f"Unsupported setting mode for {name}: {mode}"
        )


def apply_fixed_controls(synth: vita.Synth) -> None:
    controls = synth.get_controls()

    for name, setting in FIXED_CONTROLS.items():
        mode, value = setting

        set_control(
            controls=controls,
            name=name,
            mode=mode,
            value=value,
        )


def apply_sampled_parameters(
    synth: vita.Synth,
    unit_sample: np.ndarray,
    parameter_names: list[str],
) -> dict[str, Any]:
    controls = synth.get_controls()
    recorded_values: dict[str, Any] = {}

    for dimension, parameter_name in enumerate(parameter_names):
        config = PARAMS[parameter_name]

        minimum = float(config["min"])
        maximum = float(config["max"])

        unit_value = float(unit_sample[dimension])

        normalized_value = (
            minimum
            + unit_value * (maximum - minimum)
        )

        control_name = str(config["control"])
        mode = str(config["mode"])

        set_control(
            controls=controls,
            name=control_name,
            mode=mode,
            value=normalized_value,
        )

        control = controls[control_name]

        recorded_values[f"{parameter_name}_sample_01"] = (
            unit_value
        )

        recorded_values[f"{parameter_name}_normalized"] = (
            float(control.get_normalized())
        )

        recorded_values[f"{parameter_name}_raw"] = (
            float(control.value())
        )

        recorded_values[f"{parameter_name}_display"] = (
            str(synth.get_control_text(control_name))
        )

    return recorded_values


def render_sample(synth: vita.Synth) -> np.ndarray:
    audio = synth.render(
        MIDI_NOTE,
        VELOCITY,
        NOTE_DURATION,
        RENDER_DURATION,
    )

    audio = np.asarray(
        audio,
        dtype=np.float32,
    )

    expected_samples = int(
        SAMPLE_RATE * RENDER_DURATION
    )

    if audio.ndim != 2:
        raise ValueError(
            f"Expected two-dimensional audio, got {audio.shape}"
        )

    if audio.shape[0] != 2:
        raise ValueError(
            "Expected Vita stereo output shaped "
            f"(2, samples), got {audio.shape}"
        )

    if audio.shape[1] != expected_samples:
        raise ValueError(
            f"Expected {expected_samples} samples, "
            f"got {audio.shape[1]}"
        )

    if not np.all(np.isfinite(audio)):
        raise ValueError(
            "Rendered audio contains NaN or infinity."
        )

    return audio


def calculate_audio_metrics(
    audio: np.ndarray,
) -> dict[str, Any]:
    peak_value = float(
        np.max(
            np.abs(audio)
        )
    )

    rms_value = rms(audio)

    dc_offset = float(
        np.mean(audio.astype(np.float64))
    )

    dc_to_rms_ratio = (
        abs(dc_offset) / rms_value
        if rms_value > 0
        else 0.0
    )

    stereo_difference_rms = rms(
        audio[0] - audio[1]
    )

    return {
        "peak": peak_value,
        "peak_dbfs": dbfs(peak_value),
        "audio_rms": rms_value,
        "rms_dbfs": dbfs(rms_value),
        "dc_offset": dc_offset,
        "stereo_difference_rms": stereo_difference_rms,
        "is_silent": dbfs(rms_value) < SILENCE_THRESHOLD_DBFS,
        "is_clipped": peak_value >= CLIPPING_THRESHOLD,
        "dc_to_rms_ratio": dc_to_rms_ratio,
        "has_large_dc_offset": (
            abs(dc_offset) >= DC_OFFSET_WARNING_THRESHOLD
            or dc_to_rms_ratio >= DC_TO_RMS_WARNING_THRESHOLD
),
    }


def save_manifests(rows: list[dict[str, Any]]) -> None:
    dataframe = pd.DataFrame(rows)

    dataframe.to_csv(
        PILOT_MANIFEST_CSV,
        index=False,
    )

    dataframe.to_parquet(
        PILOT_MANIFEST_PARQUET,
        index=False,
    )


def save_dataset_config(
    sample_count: int,
    parameter_names: list[str],
) -> None:
    config = {
        "dataset_name": "pilot_v1",
        "created_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "sample_count": sample_count,
        "sampling_method": (
            "Scrambled Sobol sequence generated at the next "
            "power of two and truncated to the requested count."
        ),
        "sampling_seed": SAMPLING_SEED,
        "sample_rate": SAMPLE_RATE,
        "midi_note": MIDI_NOTE,
        "velocity": VELOCITY,
        "note_duration_seconds": NOTE_DURATION,
        "render_duration_seconds": RENDER_DURATION,
        "audio_format": "WAV",
        "audio_subtype": "32-bit float",
        "channels": 1,
        "parameter_order": parameter_names,
        "parameters": PARAMS,
        "fixed_controls": {
            name: {
                "mode": mode,
                "value": value,
            }
            for name, (mode, value)
            in FIXED_CONTROLS.items()
        },
        "silence_threshold_dbfs": SILENCE_THRESHOLD_DBFS,
        "clipping_threshold": CLIPPING_THRESHOLD,

        "dc_offset_warning_threshold": (
            DC_OFFSET_WARNING_THRESHOLD
        ),
        "dc_to_rms_warning_threshold": (
            DC_TO_RMS_WARNING_THRESHOLD
        ),
        
        "base_preset": str(
            BASE_PRESET.relative_to(PROJECT_ROOT)
        ),
        "base_preset_sha256": sha256_file(
            BASE_PRESET
        ),
        "versions": {
            "python": sys.version,
            "vita": version("vita"),
            "numpy": version("numpy"),
            "scipy": version("scipy"),
            "pandas": version("pandas"),
            "soundfile": version("soundfile"),
        },
    }

    CONFIG_PATH.write_text(
        json.dumps(
            config,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def save_review_list(
    rows: list[dict[str, Any]],
    seed: int,
) -> None:
    review_count = min(10, len(rows))

    rng = np.random.default_rng(seed)

    selected_indices = sorted(
        rng.choice(
            len(rows),
            size=review_count,
            replace=False,
        ).tolist()
    )

    lines = [
        "Random samples selected for manual listening:",
        "",
    ]

    for index in selected_indices:
        row = rows[index]

        lines.append(
            f"{row['sample_id']} | "
            f"{row['audio_path']} | "
            f"RMS {row['rms_dbfs']:.2f} dBFS | "
            f"Peak {row['peak_dbfs']:.2f} dBFS"
        )

    REVIEW_LIST_PATH.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    sample_count = int(args.count)

    prepare_output_directories(
        overwrite=args.overwrite
    )

    validate_configuration()

    parameter_names = list(PARAMS.keys())

    sobol_samples = create_sobol_samples(
        sample_count=sample_count,
        dimensions=len(parameter_names),
        seed=SAMPLING_SEED,
    )

    save_dataset_config(
        sample_count=sample_count,
        parameter_names=parameter_names,
    )

    rows: list[dict[str, Any]] = []
    start_time = time.perf_counter()

    print("=" * 70)
    print("VITAL PILOT DATASET GENERATION")
    print("=" * 70)
    print(f"Samples: {sample_count}")
    print(f"Parameters: {len(parameter_names)}")
    print(f"Seed: {SAMPLING_SEED}")
    print(f"Preset: {BASE_PRESET}")
    print(f"Audio output: {PILOT_AUDIO_DIR}")
    print()

    for sample_index, unit_sample in enumerate(
        sobol_samples
    ):
        sample_id = f"pilot_v1_{sample_index:05d}"

        synth = create_synth()

        if not synth.load_preset(str(BASE_PRESET)):
            raise RuntimeError(
                f"Failed to load preset for {sample_id}"
            )

        apply_fixed_controls(synth)

        parameter_values = apply_sampled_parameters(
            synth=synth,
            unit_sample=unit_sample,
            parameter_names=parameter_names,
        )

        audio = render_sample(synth)

        metrics = calculate_audio_metrics(audio)

        audio_path = (
            PILOT_AUDIO_DIR
            / f"{sample_id}.wav"
        )


        # Dataset V1 produces identical left and right channels.
        # Store one channel to avoid duplicating the same signal.
        mono_audio = audio[0]

        sf.write(
                file=audio_path,
                data=mono_audio,
                samplerate=SAMPLE_RATE,
                subtype="FLOAT",
                format="WAV",
        )


        # Dataset V1 produces identical left and right channels.
        # Store one channel to avoid duplicating the same signal.
        mono_audio = audio[0]

        sf.write(
            file=audio_path,
            data=mono_audio,
            samplerate=SAMPLE_RATE,
            subtype="FLOAT",
            format="WAV",
        )

        row: dict[str, Any] = {
            "sample_id": sample_id,
            "sample_index": sample_index,
            "audio_path": str(
                audio_path.relative_to(PROJECT_ROOT)
            ),
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "midi_note": MIDI_NOTE,
            "velocity": VELOCITY,
            "note_duration_seconds": NOTE_DURATION,
            "render_duration_seconds": RENDER_DURATION,
            **parameter_values,
            **metrics,
        }

        rows.append(row)

        completed = sample_index + 1

        if (
            completed % CHECKPOINT_INTERVAL == 0
            or completed == sample_count
        ):
            save_manifests(rows)

            elapsed = time.perf_counter() - start_time
            rate = completed / elapsed

            print(
                f"[{completed:>4}/{sample_count}] "
                f"{rate:.2f} samples/sec | "
                f"latest RMS={metrics['rms_dbfs']:.2f} dBFS | "
                f"peak={metrics['peak_dbfs']:.2f} dBFS"
            )

    elapsed = time.perf_counter() - start_time

    silent_count = sum(
        bool(row["is_silent"])
        for row in rows
    )

    clipped_count = sum(
        bool(row["is_clipped"])
        for row in rows
    )

    large_dc_count = sum(
        bool(row["has_large_dc_offset"])
        for row in rows
    )

    maximum_absolute_dc_offset = max(
        abs(float(row["dc_offset"]))
        for row in rows
    )

    maximum_dc_to_rms_ratio = max(
        float(row["dc_to_rms_ratio"])
        for row in rows
    )

    stereo_identical_count = sum(
        float(row["stereo_difference_rms"]) < 1e-10
        for row in rows
    )

    summary = {
        "sample_count": len(rows),
        "generation_seconds": elapsed,
        "samples_per_second": len(rows) / elapsed,
        "silent_samples": silent_count,
        "clipped_samples": clipped_count,
        "large_dc_offset_samples": large_dc_count,
        "maximum_absolute_dc_offset": maximum_absolute_dc_offset,
        "maximum_dc_to_rms_ratio": maximum_dc_to_rms_ratio,
        "identical_stereo_channel_samples": (
            stereo_identical_count
        ),
        "minimum_rms_dbfs": min(
            float(row["rms_dbfs"])
            for row in rows
        ),
        "maximum_rms_dbfs": max(
            float(row["rms_dbfs"])
            for row in rows
        ),
        "maximum_peak": max(
            float(row["peak"])
            for row in rows
        ),
        "audio_directory": str(PILOT_AUDIO_DIR),
        "csv_manifest": str(PILOT_MANIFEST_CSV),
        "parquet_manifest": str(
            PILOT_MANIFEST_PARQUET
        ),
    }

    SUMMARY_PATH.write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )

    save_review_list(
        rows=rows,
        seed=SAMPLING_SEED + 1,
    )

    # Confirm that the Parquet file is readable.
    verified_manifest = pd.read_parquet(
        PILOT_MANIFEST_PARQUET
    )

    if len(verified_manifest) != sample_count:
        raise RuntimeError(
            "Manifest row count does not match "
            "the requested sample count."
        )

    print()
    print("=" * 70)
    print("PILOT GENERATION COMPLETE")
    print("=" * 70)
    print(f"Generated: {len(rows)} WAV files")
    print(f"Time: {elapsed:.2f} seconds")
    print(
        f"Speed: {len(rows) / elapsed:.2f} samples/sec"
    )
    print(f"Silent samples: {silent_count}")
    print(f"Clipped samples: {clipped_count}")
    print(f"Large DC-offset samples: {large_dc_count}")
    print(
        "Maximum absolute DC offset: "
        f"{maximum_absolute_dc_offset:.6f}"
    )   
    print(
        "Maximum DC-to-RMS ratio: "
        f"{maximum_dc_to_rms_ratio:.4f}"
    )
    print(
        "Identical stereo-channel samples: "
        f"{stereo_identical_count}/{len(rows)}"
    )
    print(f"CSV: {PILOT_MANIFEST_CSV}")
    print(f"Parquet: {PILOT_MANIFEST_PARQUET}")
    print(f"Config: {CONFIG_PATH}")
    print(f"Summary: {SUMMARY_PATH}")
    print(f"Listening list: {REVIEW_LIST_PATH}")


if __name__ == "__main__":
    main()