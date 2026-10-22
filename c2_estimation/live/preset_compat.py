"""Separate, verified desktop exports. Never rewrite frozen presets or job files."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile

TARGET_VERSION = "1.6.4"
VITA_VERSION = "99999.9.9"
PATCH_NAME = "predicted_vital_1_6_4.vital"
AUDIT_NAME = "verification.json"
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
INPUT_NAMES = ("predicted.vital", "result.json", "reconstruction_float.wav")


class CompatibilityError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def convert_document(source):
    """Only replace the known Vita build marker; do not downgrade real versions."""
    document = deepcopy(source)
    if not isinstance(document, dict) or document.get("synth_version") not in (VITA_VERSION, TARGET_VERSION):
        raise CompatibilityError("This export only supports Vita's placeholder version or Vital 1.6.4.")
    settings = document.get("settings")
    tables = settings.get("wavetables") if isinstance(settings, dict) else None
    if not isinstance(tables, list) or len(tables) != 3:
        raise CompatibilityError("Expected the three-wavetable C2 preset format.")
    changes = []
    for item, key, path in [(document, "synth_version", "$.synth_version"), *[
            (table, "version", f"$.settings.wavetables[{i}].version") for i, table in enumerate(tables)]]:
        if not isinstance(item, dict) or item.get(key) not in (VITA_VERSION, TARGET_VERSION):
            raise CompatibilityError("Unsupported wavetable version; no automatic downgrade was attempted.")
        if item[key] == VITA_VERSION:
            changes.append({"path": path, "from": VITA_VERSION, "to": TARGET_VERSION})
            item[key] = TARGET_VERSION
    # Deliberately not a recursive string replacement: comments, controls and
    # embedded wavetable/sample data must remain untouched.
    return document, changes


def export_directory(output, job):
    if not JOB_ID.fullmatch(job):
        raise CompatibilityError("Invalid result ID.")
    return Path(output) / "compatibility_v1" / job / ("vital_1_6_4_" + sha(__file__)[:12])


def input_hashes(paths):
    if set(paths) != set(INPUT_NAMES):
        raise CompatibilityError("The original patch, result and float reconstruction are required.")
    return {name: sha(path) for name, path in paths.items()}


def cached_export(folder, expected_inputs):
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise CompatibilityError("Prepare the desktop export first.")
    try:
        audit = json.loads((folder / AUDIT_NAME).read_text(encoding="utf-8"))
        checks = ("non_version_json_unchanged", "all_controls_exact", "research_controls_match_saved",
                  "raw_stereo_audio_exact", "conditioned_audio_exact", "saved_reconstruction_exact")
        if (audit["status"] != "passed" or audit["target_vital_version"] != TARGET_VERSION
                or audit["converter_sha256"] != sha(__file__)
                or audit["input_sha256"] != expected_inputs
                or not all(audit[key] is True for key in checks)
                or audit["patch_sha256"] != sha(folder / PATCH_NAME)):
            raise CompatibilityError("The desktop export has changed; it will not be served.")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CompatibilityError("The desktop export is incomplete or has changed.") from exc
    return folder / PATCH_NAME, audit


def verify_pair(engine, source_path, converted_path, result, reconstruction_path):
    """Reload actual files in fresh synths; no controls are reapplied after load."""
    import numpy as np
    import soundfile as sf
    from generation.audio_processing import dc_filter
    from generation.corpus_audio import canonical_float32, sample_digest
    from generation.vital_setup import validate_synth
    from c2_estimation.v4.data import NAMES

    generator = engine.renderer.generator
    synths, values, audio = [], [], []
    for path in (source_path, converted_path):
        synth = generator.create_synth()
        if not synth.load_preset(str(path)):
            raise CompatibilityError("Vita could not reload the preset file.")
        validate_synth(synth, generator.PROFILE)
        controls = synth.get_controls()
        values.append({name: float(control.value()) for name, control in controls.items()})
        synths.append(synth)
        audio.append(generator.render_sample(synth))
    if values[0] != values[1]:
        raise CompatibilityError("Desktop export changed synthesizer controls.")
    if not np.array_equal(audio[0], audio[1]):
        raise CompatibilityError("Desktop export changed rendered audio.")
    if any(np.max(np.abs(stereo[0] - stereo[1])) > 1e-10 for stereo in audio):
        raise CompatibilityError("Unexpected stereo behavior.")
    rows = {row["name"]: row for row in result["parameters"]}
    if set(rows) != set(NAMES):
        raise CompatibilityError("Saved result does not contain the 13 C2 controls.")
    saved_control_max_error = 0.0
    # Saved UI settings are float64 requested values, while Vita readbacks are
    # float32. Use the existing profile validation tolerance only for that
    # comparison. Original-vs-copy controls/audio above remain strictly exact.
    saved_control_tolerance = 2e-6
    for synth in synths:
        for name in NAMES:
            actual = synth.get_controls()[generator.PARAMS[name]["control"]].get_normalized()
            error = abs(actual - rows[name]["vital_normalized"])
            saved_control_max_error = max(saved_control_max_error, error)
            if not np.isfinite(error) or error > saved_control_tolerance:
                raise CompatibilityError("Preset no longer matches the saved prediction: " + name)
    conditioned = [canonical_float32(dc_filter(stereo[0].copy(), 44100)) for stereo in audio]
    saved, rate = sf.read(reconstruction_path, dtype="float32")
    if (rate != 44100 or saved.shape != (132300,) or not np.array_equal(conditioned[0], conditioned[1])
            or not np.array_equal(conditioned[1], saved)
            or sample_digest(saved) != result["reconstruction_samples_sha256"]):
        raise CompatibilityError("Export does not reproduce the saved float reconstruction.")
    return {"all_controls_exact": True, "control_count": len(values[0]),
            "research_controls_match_saved": True, "research_control_count": len(NAMES),
            "saved_control_readback_tolerance": saved_control_tolerance,
            "saved_control_max_abs_error": saved_control_max_error,
            "raw_stereo_audio_exact": True, "conditioned_audio_exact": True,
            "saved_reconstruction_exact": True, "reconstruction_samples_sha256": sample_digest(saved)}


def prepare_export(engine, paths, folder):
    paths = {name: Path(path) for name, path in paths.items()}
    before = input_hashes(paths)
    folder = Path(folder)
    if folder.exists():
        return cached_export(folder, before)
    source = json.loads(paths["predicted.vital"].read_text(encoding="utf-8"))
    result = json.loads(paths["result.json"].read_text(encoding="utf-8"))
    if result.get("export_audit", {}).get("patch_sha256") != before["predicted.vital"]:
        raise CompatibilityError("Original patch does not match the saved export audit.")
    converted, changes = convert_document(source)
    restored = deepcopy(converted)
    restored["synth_version"] = source["synth_version"]
    for i, table in enumerate(source["settings"]["wavetables"]):
        restored["settings"]["wavetables"][i]["version"] = table["version"]
    if restored != source:
        raise CompatibilityError("Conversion changed fields other than version metadata.")
    # This directory is separate from immutable jobs/<id> and all research data.
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".building-", dir=folder.parent) as temp:
        staging = Path(temp)
        patch = staging / PATCH_NAME
        patch.write_text(json.dumps(converted, ensure_ascii=False, allow_nan=False,
                                    separators=(",", ":")), encoding="utf-8")
        if json.loads(patch.read_text(encoding="utf-8")) != converted:
            raise CompatibilityError("Written desktop preset differs from the verified conversion.")
        checks = verify_pair(engine, paths["predicted.vital"], patch, result, paths["reconstruction_float.wav"])
        if input_hashes(paths) != before:
            raise CompatibilityError("Original job changed during export; no export published.")
        audit = {"version": "c2-desktop-export-v1", "status": "passed",
                 "created_utc": datetime.now(timezone.utc).isoformat(),
                 "target_vital_version": TARGET_VERSION, "metadata_changes": changes,
                 "non_version_json_unchanged": True, "input_sha256": before,
                 "converter_sha256": sha(__file__), "patch_sha256": sha(patch), **checks,
                 "desktop_vital_checked": False, "desktop_audio_checked": False,
                 "note": "Vita roundtrip verified. Opening and playing in desktop Vital remains a separate check."}
        (staging / AUDIT_NAME).write_text(json.dumps(audit, indent=2), encoding="utf-8")
        # Move only this newly created, bounded staging directory; never overwrite.
        if folder.exists() or not staging.resolve().is_relative_to(folder.parent.resolve()):
            raise CompatibilityError("Desktop export destination already exists or is outside its folder.")
        staging.rename(folder)
    return cached_export(folder, before)


def checked_inputs(output, job):
    """CLI input guard equivalent to the live app's checked original downloads."""
    if not JOB_ID.fullmatch(job):
        raise CompatibilityError("Invalid result ID.")
    root = Path(output)
    if json.loads((root / "status" / (job + ".json")).read_text())["state"] != "complete":
        raise CompatibilityError("Only completed results can be exported.")
    folder = root / "jobs" / job
    manifest = json.loads((folder / "manifest.json").read_text())["files"]
    paths = {name: folder / name for name in INPUT_NAMES}
    if any(manifest.get(name) != sha(path) for name, path in paths.items()):
        raise CompatibilityError("An original job file changed; refusing export.")
    return paths


def main():
    from .engine import DEFAULT_OUTPUT, Engine
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = checked_inputs(args.output, args.job)
    patch, audit = prepare_export(Engine(device="cpu"), paths, export_directory(args.output, args.job))
    print(json.dumps({"patch": str(patch.resolve()), "audit": str(patch.with_name(AUDIT_NAME).resolve()),
                      "checks": audit}, indent=2))


if __name__ == "__main__":
    main()
