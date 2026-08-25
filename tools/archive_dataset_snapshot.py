"""Create a timestamped archive of the active pilot_v1 dataset."""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "pilot_v1"
SOURCE_AUDIO = REPO_ROOT / "data" / "raw" / "audio" / DATASET_ID
MANIFEST_DIR = REPO_ROOT / "data" / "manifests"
CONFIG_PATH = MANIFEST_DIR / f"{DATASET_ID}_config.json"
CSV_PATH = MANIFEST_DIR / f"{DATASET_ID}.csv"
ARCHIVE_ROOT = REPO_ROOT / "dataset_archive"

MANIFEST_NAMES = (
    f"{DATASET_ID}.csv",
    f"{DATASET_ID}.parquet",
    f"{DATASET_ID}_config.json",
    f"{DATASET_ID}_summary.json",
    f"{DATASET_ID}_review_samples.txt",
)

C1_OUTPUTS = (
    REPO_ROOT / "c1_timbre" / "outputs" / "c1_audio_features.csv",
    REPO_ROOT / "c1_timbre" / "outputs" / "cutoff_vs_centroid.png",
    REPO_ROOT / "c1_timbre" / "outputs" / "cutoff_vs_centroid_summary.csv",
)

C4_OUTPUTS = (
    REPO_ROOT / "c4_metric" / "development_triplets.csv",
)


class ArchiveError(RuntimeError):
    """Raised when a safe, complete snapshot cannot be created."""


def relative_display(path: Path, *, trailing_slash: bool = False) -> str:
    """Return a repository-relative path using portable separators."""
    display = path.relative_to(REPO_ROOT).as_posix()
    return f"{display}/" if trailing_slash else display


def filesystem_slug(value: str, fallback: str) -> str:
    """Convert metadata text into a short, filesystem-friendly component."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or fallback


def subtype_slug(audio_subtype: str) -> str:
    """Shorten common audio subtype names, such as 16-bit PCM to pcm16."""
    normalized = audio_subtype.lower()
    bit_depth_match = re.search(r"\b(8|16|24|32|64)\b", normalized)

    if bit_depth_match and "pcm" in normalized:
        return f"pcm{bit_depth_match.group(1)}"
    if bit_depth_match and "float" in normalized:
        return f"float{bit_depth_match.group(1)}"

    return filesystem_slug(audio_subtype, "unknown_subtype")


def load_config() -> dict[str, Any]:
    """Load and validate metadata needed to name and verify the archive."""
    if not CONFIG_PATH.is_file():
        raise ArchiveError(
            f"Required config JSON is missing: {relative_display(CONFIG_PATH)}"
        )
    if not CSV_PATH.is_file():
        raise ArchiveError(f"Required CSV manifest is missing: {relative_display(CSV_PATH)}")
    if not SOURCE_AUDIO.is_dir():
        raise ArchiveError(
            f"Required source audio directory is missing: "
            f"{relative_display(SOURCE_AUDIO, trailing_slash=True)}"
        )

    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"Could not read valid JSON from {relative_display(CONFIG_PATH)}: {exc}") from exc

    if not isinstance(config, dict):
        raise ArchiveError(f"Config JSON must contain an object: {relative_display(CONFIG_PATH)}")

    dataset_name = config.get("dataset_name")
    sample_count = config.get("sample_count")
    audio_subtype = config.get("audio_subtype")

    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise ArchiveError("Config field 'dataset_name' must be a non-empty string.")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 0:
        raise ArchiveError("Config field 'sample_count' must be a non-negative integer.")
    if not isinstance(audio_subtype, str) or not audio_subtype.strip():
        raise ArchiveError("Config field 'audio_subtype' must be a non-empty string.")

    return config


def create_archive_directory(config: dict[str, Any], created_utc: datetime) -> Path:
    """Create a unique archive directory without overwriting an older snapshot."""
    dataset = filesystem_slug(config["dataset_name"], "dataset")
    subtype = subtype_slug(config["audio_subtype"])
    prefix = f"{dataset}_{config['sample_count']}_{subtype}"
    minute_name = f"{prefix}_{created_utc:%Y%m%d_%H%M}"

    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    candidates = [minute_name, f"{prefix}_{created_utc:%Y%m%d_%H%M%S}"]

    for candidate_name in candidates:
        candidate = ARCHIVE_ROOT / candidate_name
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate

    suffix = 2
    while True:
        candidate = ARCHIVE_ROOT / f"{candidates[-1]}_{suffix}"
        try:
            candidate.mkdir()
        except FileExistsError:
            suffix += 1
            continue
        return candidate


def copy_manifests(destination: Path) -> None:
    """Copy required and optional manifest files into the snapshot."""
    destination.mkdir()
    required_names = {CSV_PATH.name, CONFIG_PATH.name}
    for name in MANIFEST_NAMES:
        source = MANIFEST_DIR / name
        if source.is_file():
            shutil.copy2(source, destination / name)
        elif name in required_names:
            raise ArchiveError(
                f"Required metadata file disappeared during archiving: "
                f"{relative_display(source)}"
            )
        else:
            print(f"WARNING: Optional metadata file is missing: {relative_display(source)}")


def copy_optional_outputs(sources: tuple[Path, ...], destination: Path) -> bool:
    """Copy the available outputs and report whether any were archived."""
    available = [source for source in sources if source.is_file()]
    if not available:
        return False

    destination.mkdir()
    for source in available:
        shutil.copy2(source, destination / source.name)
    return True


def count_wav_files(directory: Path) -> int:
    """Count WAV files recursively and case-insensitively."""
    return sum(1 for path in directory.rglob("*") if path.is_file() and path.suffix.lower() == ".wav")


def verify_archive(archive_dir: Path, expected_sample_count: int) -> int:
    """Verify required files and WAV counts, returning the archived WAV count."""
    source_wav_count = count_wav_files(SOURCE_AUDIO)
    archived_wav_count = count_wav_files(archive_dir / "audio")
    errors: list[str] = []

    if source_wav_count != archived_wav_count:
        errors.append(
            f"source WAV count ({source_wav_count}) does not match archive WAV count "
            f"({archived_wav_count})"
        )
    if archived_wav_count != expected_sample_count:
        errors.append(
            f"archive WAV count ({archived_wav_count}) does not match config sample_count "
            f"({expected_sample_count})"
        )

    archived_manifests = archive_dir / "manifests"
    if not (archived_manifests / CSV_PATH.name).is_file():
        errors.append("archived CSV manifest is missing")
    if not (archived_manifests / CONFIG_PATH.name).is_file():
        errors.append("archived config JSON is missing")

    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise ArchiveError(f"Archive verification failed:\n{details}")

    return archived_wav_count


def original_creation_utc(config: dict[str, Any]) -> str:
    """Find the creation timestamp used by known config variants."""
    for key in ("created_utc", "creation_utc", "created_at", "creation_date"):
        value = config.get(key)
        if value is not None:
            return str(value)
    return "not available"


def write_archive_info(
    archive_dir: Path,
    config: dict[str, Any],
    archive_created_utc: datetime,
    wav_count: int,
    c1_archived: bool,
    c4_archived: bool,
) -> None:
    """Write human-readable provenance and status for the snapshot."""
    info = f"""Dataset archive snapshot

Dataset name: {config['dataset_name']}
Sample count: {config['sample_count']}
Audio subtype: {config['audio_subtype']}
Sample rate: {config.get('sample_rate', 'not available')}
Channels: {config.get('channels', 'not available')}
Original creation UTC: {original_creation_utc(config)}
Archive created UTC: {archive_created_utc.isoformat()}

Source audio:
{relative_display(SOURCE_AUDIO, trailing_slash=True)}

Source manifest:
{relative_display(CSV_PATH)}

WAV files archived: {wav_count}

C1 outputs archived: {'yes' if c1_archived else 'no'}
C4 outputs archived: {'yes' if c4_archived else 'no'}

This directory is an immutable historical snapshot.
Do not edit files inside this archive.
"""
    (archive_dir / "ARCHIVE_INFO.txt").write_text(info, encoding="utf-8")


def create_snapshot() -> Path:
    """Create, verify, and document one archive snapshot."""
    config = load_config()
    archive_created_utc = datetime.now(timezone.utc)
    archive_dir = create_archive_directory(config, archive_created_utc)

    print(f"Creating archive: {relative_display(archive_dir, trailing_slash=True)}")
    try:
        shutil.copytree(SOURCE_AUDIO, archive_dir / "audio")
        copy_manifests(archive_dir / "manifests")
        c1_archived = copy_optional_outputs(C1_OUTPUTS, archive_dir / "c1_outputs")
        c4_archived = copy_optional_outputs(C4_OUTPUTS, archive_dir / "c4_outputs")
        wav_count = verify_archive(archive_dir, config["sample_count"])
        write_archive_info(
            archive_dir,
            config,
            archive_created_utc,
            wav_count,
            c1_archived,
            c4_archived,
        )
    except (ArchiveError, OSError, shutil.Error) as exc:
        raise ArchiveError(
            f"{exc}\nPartial archive was preserved at: {relative_display(archive_dir)}"
        ) from exc

    print(f"Verified {wav_count} WAV files.")
    print(f"Dataset archive created successfully: {relative_display(archive_dir)}")
    return archive_dir


def main() -> int:
    if len(sys.argv) != 1:
        print("ERROR: This utility does not take arguments.", file=sys.stderr)
        print("Usage: python tools/archive_dataset_snapshot.py", file=sys.stderr)
        return 2

    try:
        create_snapshot()
    except (ArchiveError, OSError, shutil.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
