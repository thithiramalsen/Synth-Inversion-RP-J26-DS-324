"""Single-master, process-parallel v4 runner. The historical generator stays frozen.

Run as python -B -m generation.generate_corpus --help.
Only --generate renders the corpus. --benchmark rerenders a small existing prefix
sample in memory, never writing audio. --check is read-only.
"""
from __future__ import annotations
import argparse
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import multiprocessing
import os
from pathlib import Path
import shutil
import time
import uuid

import numpy as np
import pandas as pd
import soundfile as sf
from generation.audio_processing import audio_metrics, dc_filter
from generation.corpus_audio import (PROCESSED_FLOAT_POLICY, canonical_float32,
                                     load_audio, raw_path, sample_digest)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/raw/corpus_v4"
PROFILE = "restricted_bend_sustain_v4"
CHUNK_SIZE = 128
GIB = 1024 ** 3
_GENERATOR = None


def generator():
    global _GENERATOR
    if _GENERATOR is None:
        spec = importlib.util.spec_from_file_location(
            "frozen_v4_generator", ROOT / "generation/scripts/05_generate_pilot_dataset.py")
        _GENERATOR = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_GENERATOR)
        _GENERATOR.configure_profile(PROFILE)
    return _GENERATOR


def sha(path):
    return generator().sha256_file(path)


def count_value(value):
    count = int(value)
    if count <= 0 or count & (count - 1):
        raise argparse.ArgumentTypeError("Count must be a positive power of two")
    return count


def recipe(count):
    g = generator()
    g.validate_configuration()  # Loads controls/preset; never renders.
    current = g.build_dataset_config(count, list(g.PARAMS))
    reference_path = ROOT / "reference/restricted_bend_sustain_v4_config.json"
    if not reference_path.exists():
        reference_path = g.CONFIG_PATH
    expected = json.loads(reference_path.read_text(encoding="utf-8"))
    ignored = {"sample_count", "created_utc"}
    changed = sorted(k for k in current.keys() | expected.keys()
                     if k not in ignored and current.get(k) != expected.get(k))
    if changed:
        raise ValueError(f"Frozen synthesis recipe differs: {', '.join(changed)}")
    return {
        "storage_policy": "raw_float_dc_on_read_v1",
        "synthesis": {k: v for k, v in current.items() if k not in ignored},
        "runner_sources": {name: sha(ROOT / name) for name in (
            "generation/generate_corpus.py", "generation/corpus_audio.py")},
        "sample_hash_format": "SHA256 of mono 44100 Hz, 132300 little-endian float32 samples",
        "processed_float32_policy": PROCESSED_FLOAT_POLICY,
    }


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@contextmanager
def exclusive_run():
    """OS-managed lock: automatically released even when a process crashes."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / ".run.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def verify_rows(rows, samples, *, progress=False):
    """Reject changed parameters, policy, paths, format, raw or derived audio."""
    g = generator()
    if len(rows) > len(samples):
        raise ValueError("Cannot shrink corpus")
    verifier = g.create_synth()
    if not verifier.load_preset(str(g.BASE_PRESET)):
        raise ValueError("Cannot load verifier preset")
    controls = verifier.get_controls()
    for index, row in enumerate(rows):
        if row["sample_index"] != index or row["sample_id"] != f"{PROFILE}_{index:05d}":
            raise ValueError("Checkpoint is not a contiguous Sobol prefix")
        path = raw_path(row, ROOT)
        allowed = (g.PILOT_AUDIO_DIR / "raw_float" / f"{row['sample_id']}.wav",
                   OUTPUT / "raw_float" / f"{row['sample_id']}.wav")
        if path not in tuple(p.resolve() for p in allowed):
            raise ValueError("Unexpected raw master path")
        if sha(path) != row["raw_audio_sha256"]:
            raise ValueError(f"Master file changed: {row['sample_id']}")
        load_audio(row, ROOT, verify=True)
        for dimension, (name, spec) in enumerate(g.PARAMS.items()):
            value = float(samples[index, dimension])
            if not math.isclose(value, row[name + "_sample_01"], abs_tol=1e-14, rel_tol=0):
                raise ValueError("Sobol prefix changed")
            controls[spec["control"]].set_normalized(spec["min"] + value * (spec["max"] - spec["min"]))
            for suffix, actual in (("normalized", controls[spec["control"]].get_normalized()),
                                   ("raw", controls[spec["control"]].value())):
                if not math.isclose(actual, row[name + "_" + suffix], abs_tol=2e-6, rel_tol=0):
                    raise ValueError(f"Control value changed: {row['sample_id']}/{name}")
        if progress and (index + 1) % 2048 == 0:
            print(f"Verified checkpoint rows: {index+1:,}/{len(rows):,}", flush=True)


def legacy_prefix(samples):
    g = generator()
    if not g.CONFIG_PATH.exists():
        if g.PILOT_MANIFEST_CSV.exists() or g.PILOT_AUDIO_DIR.exists():
            raise ValueError("Incomplete legacy metadata; investigate before importing")
        return []
    if not g.PILOT_MANIFEST_CSV.exists():
        raise ValueError("Legacy configuration exists without manifest")
    old = g.load_resume_rows(g.build_dataset_config(len(samples), list(g.PARAMS)), samples)
    rows = []
    for row in old:
        raw = sf.read(ROOT / row["raw_audio_path"], dtype="float32")[0]
        processed = sf.read(ROOT / row["audio_path"], dtype="float32")[0]
        derived = dc_filter(raw, g.SAMPLE_RATE).astype(np.float32)
        if not np.array_equal(processed, derived):
            raise ValueError("Historical processed audio cannot be reproduced")
        row = {k: v for k, v in row.items() if k not in ("audio_path", "audio_sha256")}
        row.update(raw_samples_sha256=sample_digest(raw),
                   processed_samples_sha256=sample_digest(derived))
        rows.append(row)
    return rows


def inspect(count):
    signature = recipe(count)
    g = generator()
    samples = g.create_sobol_samples(count, len(g.PARAMS), g.SAMPLING_SEED)
    config_path = OUTPUT / "recipe.json"
    rows = []
    if config_path.exists():
        if json.loads(config_path.read_text(encoding="utf-8")) != signature:
            raise ValueError("Corpus recipe/runtime/runner changed; do not bypass this check")
        for path in sorted((OUTPUT / "chunks").glob("*.json")):
            chunk = json.loads(path.read_text(encoding="utf-8"))
            if not chunk or path.stem != f"{len(rows):06d}":
                raise ValueError("Missing, overlapping or misnamed checkpoint chunk")
            rows.extend(chunk)
        if not rows and g.CONFIG_PATH.exists():
            # Recover an interruption between creating recipe.json and atomically
            # committing the imported legacy prefix. No existing WAV is rewritten.
            rows = legacy_prefix(samples)
        verify_rows(rows, samples)
    else:
        if OUTPUT.exists() and any(p.name != ".run.lock" for p in OUTPUT.iterdir()):
            raise ValueError("Output exists without a recipe; investigate before proceeding")
        rows = legacy_prefix(samples)
    # Hard interruptions may leave a few complete masters past the last chunk.
    # They are adopted ONLY if an independent rerender matches on resume.
    referenced = {raw_path(row, ROOT) for row in rows}
    orphans = []
    for path in (OUTPUT / "raw_float").glob("*.wav"):
        if path.resolve() not in referenced:
            try:
                index = int(path.stem.removeprefix(PROFILE + "_"))
            except ValueError:
                raise ValueError(f"Unknown uncheckpointed file: {path}") from None
            if not len(rows) <= index < count or path.name != f"{PROFILE}_{index:05d}.wav":
                raise ValueError(f"Unexpected uncheckpointed file: {path}")
            orphans.append(path)
    return signature, samples, rows, len(orphans)


def storage_check(count, existing):
    ancestor = OUTPUT
    while not ancestor.exists():
        ancestor = ancestor.parent
    free = shutil.disk_usage(ancestor).free
    remaining = count - existing
    required = remaining * (132300 * 4 + 4096) + (10 * GIB if remaining else 0)
    print(f"Existing {existing:,}; additional {remaining:,}; need {required/GIB:.1f} GiB "
          f"including headroom; free {free/GIB:.1f} GiB.", flush=True)
    if free < required:
        raise ValueError("Insufficient free storage")


def render_one(task):
    """Isolated worker: fresh synth every row, never writes shared files."""
    index, unit_sample = task
    g = generator()
    synth = g.create_synth()
    if not synth.load_preset(str(g.BASE_PRESET)):
        raise ValueError("Cannot load frozen preset")
    g.apply_fixed_controls(synth)
    parameters = g.apply_sampled_parameters(synth, np.asarray(unit_sample), list(g.PARAMS))
    stereo = g.render_sample(synth)
    if g.calculate_audio_metrics(stereo)["stereo_difference_rms"] > 1e-10:
        raise ValueError("Unexpected stereo difference")
    raw = stereo[0].copy()
    processed = dc_filter(raw, g.SAMPLE_RATE)
    row = dict(sample_id=f"{PROFILE}_{index:05d}", sample_index=index,
               sample_rate=g.SAMPLE_RATE, channels=1, midi_note=g.MIDI_NOTE, velocity=g.VELOCITY,
               note_duration_seconds=g.NOTE_DURATION, render_duration_seconds=g.RENDER_DURATION,
               audio_policy_id=g.PROFILE.AUDIO_POLICY_ID, **parameters,
               **g.calculate_audio_metrics(np.stack([processed, processed])),
               **{"raw_" + k: v for k, v in audio_metrics(raw, g.SAMPLE_RATE).items()},
               raw_samples_sha256=sample_digest(raw),
               processed_samples_sha256=sample_digest(canonical_float32(processed)))
    return row, raw


def ordered_results(tasks, workers):
    """Bounded queue; deterministic commit order regardless of completion order."""
    if workers == 1:
        for task in tasks:
            yield render_one(task)
        return
    # These limits apply before child interpreters import numerical libraries.
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    executor = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
    pending = deque()
    tasks = iter(tasks)
    try:
        for _ in range(workers * 2):
            task = next(tasks, None)
            if task is not None:
                pending.append(executor.submit(render_one, task))
        while pending:
            yield pending.popleft().result()
            task = next(tasks, None)
            if task is not None:
                pending.append(executor.submit(render_one, task))
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def save_master(row, audio):
    path = OUTPUT / "raw_float" / f"{row['sample_id']}.wav"
    if path.exists():
        info = sf.info(path)
        existing = sf.read(path, dtype="float32")[0]
        if (info.subtype != "FLOAT" or info.samplerate != 44100 or info.channels != 1
                or info.frames != 132300 or not np.array_equal(existing, audio)):
            raise ValueError(f"Uncheckpointed master differs; not overwriting: {path}")
    else:
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        sf.write(temporary, audio, 44100, subtype="FLOAT", format="WAV")
        os.replace(temporary, path)
    row.update(raw_audio_path=path.relative_to(ROOT).as_posix(), raw_audio_sha256=sha(path))


def commit(rows):
    if not rows:
        return
    path = OUTPUT / "chunks" / f"{rows[0]['sample_index']:06d}.json"
    if path.exists():
        raise FileExistsError(f"Refusing to replace checkpoint {path}")
    atomic_json(path, rows)


def finish(rows, elapsed, new_count):
    # Chunks are authoritative. Flat manifests are rebuilt only at completion.
    frame = pd.DataFrame(rows)
    for suffix in ("csv", "parquet"):
        destination = OUTPUT / f"manifest.{suffix}"
        temporary = destination.with_suffix("." + suffix + ".tmp")
        if suffix == "csv":
            frame.to_csv(temporary, index=False)
        else:
            frame.to_parquet(temporary, index=False)
        os.replace(temporary, destination)
    atomic_json(OUTPUT / "summary.json", {
        "count": len(rows), "new_render_count": new_count, "elapsed_seconds": elapsed,
        "sounds_per_second": new_count / elapsed if elapsed else None,
        **{flag: sum(bool(row[flag]) for row in rows)
           for flag in ("is_silent", "is_clipped", "has_large_dc_offset")},
        "storage": "raw FLOAT only for new rows; DC-corrected audio derived on read",
    })


def generate(count, workers):
    with exclusive_run():
        signature, samples, rows, orphans = inspect(count)
        storage_check(count, len(rows))
        (OUTPUT / "chunks").mkdir(exist_ok=True)
        (OUTPUT / "raw_float").mkdir(exist_ok=True)
        if not (OUTPUT / "recipe.json").exists():
            atomic_json(OUTPUT / "recipe.json", signature)
        if rows and not any((OUTPUT / "chunks").glob("*.json")):
            commit(rows)  # Import the entire existing prefix in one atomic commit.
        initial = len(rows)
        start_time = time.perf_counter()
        pending = []
        print(f"Workers: {workers}. {orphans} uncheckpointed masters will be compared before adoption.", flush=True)
        try:
            tasks = ((i, samples[i]) for i in range(initial, count))
            for row, audio in ordered_results(tasks, workers):
                save_master(row, audio)
                pending.append(row)
                rows.append(row)
                if len(pending) == CHUNK_SIZE:
                    commit(pending)
                    pending = []
                    elapsed = time.perf_counter() - start_time
                    done = len(rows) - initial
                    rate = done / elapsed
                    print(f"{len(rows):,}/{count:,} | {rate:.2f}/s | "
                          f"ETA {(count-len(rows))/rate/3600:.2f} h | checkpoint saved", flush=True)
        finally:
            # Controlled stop/error preserves all successfully written, ordered rows.
            commit(pending)
        finish(rows, time.perf_counter() - start_time, len(rows) - initial)
        print(f"Complete: {len(rows):,} rows. Run --check again and review summary.json.")


def benchmark(count):
    _, samples, rows, _ = inspect(count)
    if len(rows) < 32:
        raise ValueError("Benchmark needs at least 32 verified existing sounds")
    indices = np.linspace(0, len(rows)-1, 32, dtype=int)
    results = []
    for workers in (1, 4, 8):
        start = time.perf_counter()
        for (row, raw), index in zip(ordered_results(((int(i), samples[i]) for i in indices), workers), indices):
            reference = rows[int(index)]
            for key in ("raw_samples_sha256", "processed_samples_sha256"):
                if row[key] != reference[key]:
                    raise ValueError(f"Benchmark audio mismatch: workers={workers}, index={index}, {key}")
            for name in generator().PARAMS:
                for suffix in ("sample_01", "normalized", "raw"):
                    key = name + "_" + suffix
                    if row[key] != reference[key]:
                        raise ValueError(f"Benchmark parameter mismatch: {key}")
        elapsed = time.perf_counter() - start
        result = dict(workers=workers, clips=32, seconds=elapsed, clips_per_second=32/elapsed)
        results.append(result)
        print(json.dumps(result), flush=True)
    print("PASS: all benchmark waveforms and controls match. No audio files written.")
    print("Includes worker startup; excludes disk/checkpoint time and sustained thermal effects.")


def reference(rows):
    return {row["sample_id"]: [row["raw_samples_sha256"], row["processed_samples_sha256"]] for row in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=count_value, default=131072)
    parser.add_argument("--workers", type=int, default=4)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--benchmark", action="store_true")
    mode.add_argument("--export-reference", type=Path)
    mode.add_argument("--verify-reference", type=Path)
    args = parser.parse_args()
    if not 1 <= args.workers <= 32:
        parser.error("Workers must be between 1 and 32")
    if args.generate:
        generate(args.count, args.workers)
    elif args.benchmark:
        benchmark(args.count)
    else:
        _, _, rows, orphans = inspect(args.count)
        if args.check:
            storage_check(args.count, len(rows))
            print(f"PASS: {len(rows):,} verified rows; {orphans} recoverable uncheckpointed masters. No writes/renders.")
        else:
            if len(rows) != args.count or orphans:
                raise ValueError("Finish and verify the corpus before full comparison")
            if args.export_reference:
                with args.export_reference.open("x", encoding="utf-8") as handle:
                    json.dump(reference(rows), handle, sort_keys=True)
                print("Exported portable raw + processed waveform hashes; no audio exported.")
            else:
                expected = json.loads(args.verify_reference.read_text(encoding="utf-8"))
                if expected != reference(rows):
                    raise ValueError("Full-corpus waveform reference differs")
                print("PASS: every raw and processed waveform matches the shared reference.")


if __name__ == "__main__":
    main()
