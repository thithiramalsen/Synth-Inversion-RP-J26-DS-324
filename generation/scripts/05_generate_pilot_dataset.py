from __future__ import annotations

import argparse
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

from generation.bend_sustain_config import (  # noqa: E402
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
from generation.vital_setup import DEFAULT_PROFILE, PROFILES, load_profile, set_sample_rate, validate_synth  # noqa: E402


SILENCE_THRESHOLD_DBFS = -60.0
CLIPPING_THRESHOLD = 1.0
DC_OFFSET_WARNING_THRESHOLD = 0.005
DC_TO_RMS_WARNING_THRESHOLD = 0.20
CHECKPOINT_INTERVAL = 1024
PROGRESS_UPDATE_INTERVAL = 32
PROGRESS_BAR_WIDTH = 8
_LAST_PROGRESS_LINE_LENGTH = 0

PROFILE = load_profile(DEFAULT_PROFILE)
DATASET_NAME = PROFILE.DATASET_NAME
CONFIG_PATH = PILOT_MANIFEST_CSV.parent / f"{DATASET_NAME}_config.json"
SUMMARY_PATH = PILOT_MANIFEST_CSV.parent / f"{DATASET_NAME}_summary.json"
REVIEW_LIST_PATH = PILOT_MANIFEST_CSV.parent / f"{DATASET_NAME}_review_samples.txt"


def configure_profile(name: str) -> None:
    global PROFILE, DATASET_NAME, CONFIG_PATH, SUMMARY_PATH, REVIEW_LIST_PATH
    PROFILE = load_profile(name)
    fields = ("BASE_PRESET", "FIXED_CONTROLS", "MIDI_NOTE", "NOTE_DURATION", "PARAMS",
              "PILOT_AUDIO_DIR", "PILOT_MANIFEST_CSV", "PILOT_MANIFEST_PARQUET",
              "PILOT_SAMPLE_COUNT", "RENDER_DURATION", "SAMPLE_RATE", "SAMPLING_SEED", "VELOCITY")
    globals().update({field: getattr(PROFILE, field) for field in fields})
    DATASET_NAME = PROFILE.DATASET_NAME
    CONFIG_PATH = PILOT_MANIFEST_CSV.parent / f"{DATASET_NAME}_config.json"
    SUMMARY_PATH = PILOT_MANIFEST_CSV.parent / f"{DATASET_NAME}_summary.json"
    REVIEW_LIST_PATH = PILOT_MANIFEST_CSV.parent / f"{DATASET_NAME}_review_samples.txt"


# Sample rate helper function for Vita synths that support it. Some versions of Vita do not have this method.
def create_synth() -> vita.Synth:
    """Create a Vita synth and set the sample rate when supported."""
    synth = vita.Synth()

    set_sample_rate(synth, SAMPLE_RATE)

    return synth


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or extend a versioned Vital dataset. Defaults to the selected 13-control candidate."
    )
    parser.add_argument("--profile", choices=tuple(PROFILES), default=DEFAULT_PROFILE)

    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Total target count, including existing rows on resume; default is the profile's count.",
    )

    existing = parser.add_mutually_exclusive_group()
    existing.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete and replace an existing pilot dataset.",
    )
    existing.add_argument("--resume", action="store_true", help="Verify saved configuration/WAV hashes and render only missing Sobol rows.")

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


def format_duration(seconds: float) -> str:
    """Format an elapsed or estimated duration for the progress display."""
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def progress_bar(completed: int, total: int) -> str:
    """Build a small dependency-free text progress bar."""
    ratio = min(1.0, completed / total)
    filled = int(ratio * PROGRESS_BAR_WIDTH)
    if completed > 0 and filled == 0:
        filled = 1
    return f"[{'#' * filled}{'-' * (PROGRESS_BAR_WIDTH - filled)}]"


def format_progress(
    completed: int,
    total: int,
    elapsed: float,
) -> str:
    """Show progress within the current checkpoint block and overall."""
    block_number = ((completed - 1) // CHECKPOINT_INTERVAL) + 1
    total_blocks = math.ceil(total / CHECKPOINT_INTERVAL)
    block_start = (block_number - 1) * CHECKPOINT_INTERVAL
    block_size = min(CHECKPOINT_INTERVAL, total - block_start)
    block_completed = completed - block_start

    rate = completed / elapsed if elapsed > 0 else 0.0
    remaining = total - completed
    eta = remaining / rate if rate > 0 else 0.0
    overall_percent = 100.0 * completed / total

    return (
        f"Block {block_number}/{total_blocks} "
        f"{progress_bar(block_completed, block_size)} "
        f"{block_completed:,}/{block_size:,} | "
        f"Overall {progress_bar(completed, total)} "
        f"{completed:,}/{total:,} {overall_percent:.1f}% | "
        f"{rate:.2f}/sec | "
        f"{format_duration(elapsed)} elapsed | "
        f"ETA {format_duration(eta)}"
    )


def print_progress(line: str, *, complete_line: bool) -> None:
    """Update one terminal line, or emit checkpoint lines in redirected logs."""
    global _LAST_PROGRESS_LINE_LENGTH

    if sys.stdout.isatty():
        end = "\n" if complete_line else ""
        print(
            f"\r{line.ljust(_LAST_PROGRESS_LINE_LENGTH)}",
            end=end,
            flush=True,
        )
        _LAST_PROGRESS_LINE_LENGTH = (
            0 if complete_line else len(line)
        )
    elif complete_line:
        print(line, flush=True)


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
    expected = (PROJECT_ROOT / "data/raw/audio" / DATASET_NAME).resolve()
    if PILOT_AUDIO_DIR.resolve() != expected or expected.parent != (PROJECT_ROOT / "data/raw/audio").resolve():
        raise ValueError("Audio output is outside the selected dataset directory")
    if not overwrite and any(p.exists() for p in (PILOT_MANIFEST_CSV, PILOT_MANIFEST_PARQUET, CONFIG_PATH)):
        raise FileExistsError("Dataset metadata already exists. Use --resume or select a new dataset version.")
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
    validate_synth(synth, PROFILE)


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
    csv_temp = PILOT_MANIFEST_CSV.with_suffix(".csv.tmp")
    parquet_temp = PILOT_MANIFEST_PARQUET.with_suffix(".parquet.tmp")
    dataframe.to_csv(csv_temp, index=False)
    dataframe.to_parquet(parquet_temp, index=False)
    parquet_temp.replace(PILOT_MANIFEST_PARQUET)
    csv_temp.replace(PILOT_MANIFEST_CSV)


def build_dataset_config(
    sample_count: int,
    parameter_names: list[str],
) -> dict[str, Any]:
    config = {
        "dataset_name": DATASET_NAME,
        "schema_status": PROFILE.SCHEMA_STATUS,
        "modulations": list(PROFILE.MODULATIONS),
        "generator_sha256": sha256_file(Path(__file__)),
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
        "audio_subtype": "16-bit PCM",
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
    if getattr(PROFILE, "AUDIO_POLICY_ID", None):
        from generation.audio_processing import policy_definition
        config["audio_processing"] = policy_definition()
        config["audio_policy_id"] = PROFILE.AUDIO_POLICY_ID
        config["audio_subtype"] = "32-bit FLOAT (DC conditioned); raw FLOAT preserved separately"
    return config


def save_dataset_config(config: dict[str, Any]) -> None:
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")
    temporary.replace(CONFIG_PATH)


def load_resume_rows(config: dict[str, Any], samples: np.ndarray) -> list[dict[str, Any]]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("Cannot resume without a saved dataset configuration")
    previous = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    # Count and creation time may change when extending the same Sobol prefix.
    ignored = {"sample_count", "created_utc"}
    before = {k: v for k, v in previous.items() if k not in ignored}
    after = {k: v for k, v in config.items() if k not in ignored}
    if before != after:
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        raise ValueError(f"Resume configuration changed ({', '.join(changed)}). Use a new dataset version.")
    config["created_utc"] = previous["created_utc"]
    display_types = {f"{name}_display": str for name in PARAMS}
    rows = (pd.read_csv(PILOT_MANIFEST_CSV, dtype=display_types, float_precision="round_trip").to_dict("records")
            if PILOT_MANIFEST_CSV.exists() else [])
    if len(rows) > len(samples):
        raise ValueError("Cannot shrink an existing dataset")
    verifier = create_synth()
    if not verifier.load_preset(str(BASE_PRESET)):
        raise ValueError("Cannot verify saved parameter values")
    controls = verifier.get_controls()
    for index, row in enumerate(rows):
        sample_id = f"{DATASET_NAME}_{index:05d}"
        if row["sample_id"] != sample_id or row["sample_index"] != index:
            raise ValueError("Saved manifest is not a contiguous Sobol prefix")
        expected_path = PILOT_AUDIO_DIR / f"{sample_id}.wav"
        if (PROJECT_ROOT / row["audio_path"]).resolve() != expected_path.resolve():
            raise ValueError(f"Unexpected audio path for {sample_id}")
        if not expected_path.exists() or row.get("audio_sha256") != sha256_file(expected_path):
            raise ValueError(f"Missing or modified saved WAV: {sample_id}")
        if getattr(PROFILE, "AUDIO_POLICY_ID", None):
            raw_path = PILOT_AUDIO_DIR / "raw_float" / f"{sample_id}.wav"
            if (row.get("audio_policy_id") != PROFILE.AUDIO_POLICY_ID
                    or (PROJECT_ROOT / row.get("raw_audio_path", "")).resolve() != raw_path.resolve()
                    or not raw_path.is_file() or row.get("raw_audio_sha256") != sha256_file(raw_path)):
                raise ValueError(f"Missing or modified raw WAV/policy: {sample_id}")
        for dimension, name in enumerate(PARAMS):
            if not math.isclose(float(row[f"{name}_sample_01"]), samples[index, dimension], abs_tol=1e-14, rel_tol=0):
                raise ValueError(f"Sobol prefix mismatch for {sample_id}/{name}")
            spec = PARAMS[name]
            expected = spec["min"] + samples[index, dimension] * (spec["max"] - spec["min"])
            control = controls[spec["control"]]
            control.set_normalized(float(expected))
            for suffix, actual in (("normalized", control.get_normalized()), ("raw", control.value())):
                if not math.isclose(float(row[f"{name}_{suffix}"]), actual, abs_tol=2e-6, rel_tol=0):
                    raise ValueError(f"Saved parameter value changed: {sample_id}/{name}_{suffix}")
        for flag in ("is_silent", "is_clipped", "has_large_dc_offset"):
            if not isinstance(row[flag], (bool, np.bool_)):
                raise ValueError(f"Invalid boolean QA field: {sample_id}/{flag}")
    # A crash can leave WAVs after the last manifest checkpoint. They are not
    # overwritten silently; inspect/archive these files before resuming.
    expected_names = {f"{row['sample_id']}.wav" for row in rows}
    extra = {p.name for p in PILOT_AUDIO_DIR.glob("*.wav")} - expected_names
    if extra:
        raise ValueError(f"Found {len(extra)} uncheckpointed WAV(s); inspect/archive them before resuming")
    if getattr(PROFILE, "AUDIO_POLICY_ID", None):
        extra_raw = {p.name for p in (PILOT_AUDIO_DIR / "raw_float").glob("*.wav")} - expected_names
        if extra_raw:
            raise ValueError("Found uncheckpointed raw WAV(s); inspect/archive them before resuming")
    return rows


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
    configure_profile(args.profile)
    sample_count = PILOT_SAMPLE_COUNT if args.count is None else int(args.count)
    if sample_count <= 0:
        raise ValueError("Count must be positive")
    if DATASET_NAME != "pilot_v1" and sample_count & (sample_count - 1):
        raise ValueError(f"{DATASET_NAME} requires a power-of-two total count (e.g. 1024 or 131072)")
    # Validate before any output can be replaced.
    validate_configuration()

    parameter_names = list(PARAMS.keys())

    sobol_samples = create_sobol_samples(
        sample_count=sample_count,
        dimensions=len(parameter_names),
        seed=SAMPLING_SEED,
    )

    config = build_dataset_config(
        sample_count=sample_count,
        parameter_names=parameter_names,
    )

    if args.resume:
        rows = load_resume_rows(config, sobol_samples)
    else:
        prepare_output_directories(overwrite=args.overwrite)
        rows = []
    initial_count = len(rows)
    if initial_count == sample_count:
        print(f"Verified all {sample_count} existing WAVs; nothing to render.")
        return
    save_dataset_config(config)
    start_time = time.perf_counter()

    print("=" * 70)
    print(f"VITAL DATASET GENERATION: {DATASET_NAME}")
    print("=" * 70)
    print(f"Samples: {sample_count}")
    print(f"Parameters: {len(parameter_names)}")
    print(f"Schema status: {PROFILE.SCHEMA_STATUS}; preserving {initial_count} existing rows")
    print(f"Seed: {SAMPLING_SEED}")
    print(f"Preset: {BASE_PRESET}")
    print(f"Audio output: {PILOT_AUDIO_DIR}")
    print(
        f"Progress: {math.ceil(sample_count / CHECKPOINT_INTERVAL)} block(s), "
        f"up to {CHECKPOINT_INTERVAL:,} samples each; "
        f"live updates every {PROGRESS_UPDATE_INTERVAL} samples"
    )
    print()

    for sample_index, unit_sample in enumerate(
        sobol_samples[initial_count:], start=initial_count
    ):
        sample_id = f"{DATASET_NAME}_{sample_index:05d}"

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


        if metrics["stereo_difference_rms"] > 1e-10:
            raise ValueError(f"Stereo channels differ in the declared mono domain: {sample_id}")
        mono_audio = audio[0]
        processing = {}
        subtype = "PCM_16"
        if getattr(PROFILE, "AUDIO_POLICY_ID", None):
            from generation.audio_processing import audio_metrics, dc_filter
            raw_path = PILOT_AUDIO_DIR / "raw_float" / f"{sample_id}.wav"
            raw_path.parent.mkdir(exist_ok=True)
            sf.write(raw_path, mono_audio, SAMPLE_RATE, subtype="FLOAT")
            raw_metrics = audio_metrics(mono_audio, SAMPLE_RATE)
            mono_audio = dc_filter(mono_audio, SAMPLE_RATE)
            metrics = calculate_audio_metrics(np.stack([mono_audio, mono_audio]))
            processing = {"audio_policy_id": PROFILE.AUDIO_POLICY_ID,
                          "raw_audio_path": str(raw_path.relative_to(PROJECT_ROOT)),
                          "raw_audio_sha256": sha256_file(raw_path),
                          **{f"raw_{key}": value for key, value in raw_metrics.items()}}
            subtype = "FLOAT"

        sf.write(
            file=audio_path,
            data=mono_audio,
            samplerate=SAMPLE_RATE,
            subtype=subtype,
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
            "audio_sha256": sha256_file(audio_path),
            **parameter_values,
            **metrics,
            **processing,
        }

        rows.append(row)

        completed = sample_index + 1

        is_checkpoint = (
            completed % CHECKPOINT_INTERVAL == 0
            or completed == sample_count
        )

        if is_checkpoint:
            save_manifests(rows)

        if (
            is_checkpoint
            or completed % PROGRESS_UPDATE_INTERVAL == 0
        ):
            elapsed = time.perf_counter() - start_time
            # Progress is for new renders; the absolute checkpoint count is shown above.
            progress = format_progress(
                completed=completed - initial_count,
                total=sample_count - initial_count,
                elapsed=elapsed,
            )

            if is_checkpoint:
                progress += (
                    " | checkpoint saved | "
                    f"RMS={metrics['rms_dbfs']:.2f} dBFS | "
                    f"peak={metrics['peak_dbfs']:.2f} dBFS"
                )

            print_progress(
                progress,
                complete_line=is_checkpoint,
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
        "dataset_name": DATASET_NAME,
        "schema_status": PROFILE.SCHEMA_STATUS,
        "preserved_samples": initial_count,
        "new_render_count": len(rows) - initial_count,
        "generation_seconds": elapsed,
        "samples_per_second": (len(rows) - initial_count) / elapsed,
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
    print(f"Total: {len(rows)} WAV files; newly rendered: {len(rows) - initial_count}")
    print(f"Time: {elapsed:.2f} seconds")
    print(
        f"Speed: {(len(rows) - initial_count) / elapsed:.2f} samples/sec"
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
