"""Prepare a fresh Git clone for the frozen v4 dataset; never render audio.

Uses only the standard library. The private share ZIP restores the exact frozen
source bytes, preset and reference tables. Git line-ending conversion is therefore
irrelevant to the synthesis fingerprint. Existing datasets or edited files stop
setup. Old tracked pilot metadata is backed up, not used as local render state.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


BUNDLE_SHA256 = "c772f1da490a8d8acd00c452e8dbfc85619e577f024008d6839966c5d5cf24d8"
FILES = (
    "requirements.txt",
    "generation/params_config.py",
    "generation/restricted_config.py",
    "generation/bend_config.py",
    "generation/bend_sustain_config.py",
    "generation/vital_setup.py",
    "generation/audio_processing.py",
    "generation/audio_policies/dc_highpass_10hz_v1.json",
    "generation/scripts/05_generate_pilot_dataset.py",
    "generation/presets/base_restricted_bend_sustain_v4.vital",
    "generation/verify_reproduction.py",
    "generation/generate_corpus.py",
    "generation/corpus_audio.py",
    "generation/repair_corpus_float_policy.py",
    "generation/verify_parameter_reference.py",
    "generation/audit_full_corpus.py",
    "reference/restricted_bend_sustain_v4_config.json",
    "reference/parameters_normalized.parquet",
    "reference/parameters_full.parquet",
    "reference/full_waveform_reference.json",
    "reference/reference_recipe.json",
    "reference/reference_summary.json",
    "reference/corpus_verification.json",
)
PILOT_METADATA = tuple("data/manifests/restricted_bend_sustain_v4" + ending for ending in (
    ".csv", ".parquet", "_config.json", "_summary.json", "_review_samples.txt"))


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_path(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Path escapes clone: {relative}")
    return path


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=False)


def validate_clone(root):
    result = git(root, "rev-parse", "--show-toplevel")
    if result.returncode or Path(result.stdout.strip()).resolve() != root:
        raise ValueError("Choose the root of a fresh, non-bare Git clone")
    for relative in ("data/raw/corpus_v4", "data/raw/audio/restricted_bend_sustain_v4"):
        if local_path(root, relative).exists():
            raise ValueError(f"Existing dataset directory: {relative}. Use a fresh clone; nothing was changed.")


def require_clean_file(root, relative):
    tracked = git(root, "ls-files", "--error-unmatch", "--", relative)
    if tracked.returncode or git(root, "diff", "--quiet", "HEAD", "--", relative).returncode:
        raise ValueError(f"Preserving existing/uncommitted file: {relative}. Use a fresh clone.")


def prepare(bundle, root, apply=False, *, expected_sha=BUNDLE_SHA256):
    root = root.resolve()
    validate_clone(root)
    if checksum(bundle) != expected_sha:
        raise ValueError("Share ZIP checksum differs. Use the exact team_v4_131072_SHARE.zip supplied by Thithira.")
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        integrity = json.loads(archive.read("reference/package_integrity.json"))["files"]["recipe"]
        payload = {}
        for relative in FILES:
            content = archive.read(relative)
            if hashlib.sha256(content).hexdigest() != integrity[relative]:
                raise ValueError(f"Bundle member checksum differs: {relative}")
            payload[relative] = content
    changed = []
    for relative in FILES:
        path = local_path(root, relative)
        if path.exists():
            if not path.is_file():
                raise ValueError(f"Expected a file: {relative}")
            if checksum(path) == integrity[relative]:
                continue
            require_clean_file(root, relative)
        changed.append(relative)
    metadata = []
    for relative in PILOT_METADATA:
        path = local_path(root, relative)
        if path.exists():
            if not path.is_file():
                raise ValueError(f"Expected metadata file: {relative}")
            require_clean_file(root, relative)
            metadata.append(relative)
    reference = {"files": {"recipe": {name: integrity[name] for name in FILES},
                            "candidates": {}, "pilot": {}}}
    reference_path = local_path(root, "reference/clone_integrity.json")
    if reference_path.exists() and json.loads(reference_path.read_text(encoding="utf-8")) != reference:
        raise ValueError("Existing clone integrity reference differs; nothing was changed")
    print(f"Verified private ZIP. Restore {len(changed)} frozen files; preserve {len(metadata)} pilot metadata files.")
    if not apply:
        print("CHECK ONLY: no files changed. Add --apply to prepare this fresh clone.")
        return
    if changed or metadata:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = local_path(root, f"data/processed/team_clone_setup_{stamp}")
        backup.mkdir(parents=True, exist_ok=False)
        # Back up every existing file before replacing/removing any of them.
        for relative in changed + metadata:
            source = local_path(root, relative)
            if source.exists():
                target = local_path(root, str(backup.relative_to(root) / relative))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if checksum(source) != checksum(target):
                    raise ValueError(f"Backup verification failed: {relative}")
        for relative in changed:
            target = local_path(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload[relative])
        for relative in metadata:
            local_path(root, relative).unlink()  # A verified backup now holds the original bytes.
        (backup / "setup.json").write_text(json.dumps({"bundle_sha256": expected_sha,
            "restored": changed, "archived_metadata": metadata}, indent=2), encoding="utf-8")
        print(f"Original files preserved in {backup.relative_to(root)}")
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_text(json.dumps(reference, indent=2), encoding="utf-8")
    print("READY: install the pinned environment, then run --check and --generate.")
    print("This PC will generate all 131,072 from index zero. No audio was generated by setup.")
    print("Keep this frozen folder unchanged until generation and verification finish.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        prepare(args.bundle, args.root, args.apply)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Setup stopped: {exc}\n")
