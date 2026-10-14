"""Build real-corpus CLAP triplets and clearly synthetic responses for rehearsal.

The 131,072 WAV corpus is the source. By default only a seeded 1,024-sound subset
is CLAP-embedded. Synthetic choices are generated independently of CLAP scores and
are never evidence about human preference or metric validity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_MANIFEST = ROOT / "data/raw/corpus_v4/manifest.csv"
OUTPUT_RESPONSES = HERE / "dummy_c4_responses.csv"
OUTPUT_TRIPLETS = HERE / "clap_triplets.csv"
OUTPUT_CACHE = HERE / "clap_embedding_cache.npz"
OUTPUT_META = HERE / "clap_embedding_cache.json"
STIMULI_DIR = HERE / "stimuli"
MODEL_ID = "laion/clap-htsat-unfused"
DEFAULT_MODEL_REVISION = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"
SYNTHETIC_MARK = "SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows_from_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_manifest(path: Path, expected_count: int) -> list[dict[str, str]]:
    rows = rows_from_csv(path)
    if len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count:,} corpus rows in {path}; found {len(rows):,}")
    required = {"sample_id", "raw_audio_path", "processed_samples_sha256", "audio_policy_id"}
    if not required.issubset(rows[0]):
        raise ValueError(f"Corpus manifest is missing columns: {sorted(required - set(rows[0]))}")
    return rows


def normalized_parameters(row: dict[str, str], names: list[str]) -> np.ndarray:
    return np.asarray([float(row[f"{name}_sample_01"]) for name in names], dtype=np.float32)


def preprocess_pool(pool: list[dict[str, str]], temp_dir: Path) -> tuple[list[str], list[Path], list[float]]:
    """Apply the repo's DC policy and one shared held-RMS level target."""
    from generation.audio_processing import apply_level, audio_metrics, dc_filter, level_plan
    from generation.corpus_audio import read_raw

    metrics = []
    for row in pool:
        raw = read_raw(row, ROOT)
        dc = dc_filter(raw, 44100)
        metrics.append(audio_metrics(dc, 44100))
        del raw, dc
    plan = level_plan(metrics)
    paths = []
    for row, gain in zip(pool, plan["gains"]):
        audio = dc_filter(read_raw(row, ROOT), 44100)
        conditioned = apply_level(audio, gain, input_policy_id=row["audio_policy_id"])
        path = temp_dir / f"{row['sample_id']}.wav"
        sf.write(path, conditioned, 44100, subtype="PCM_16")
        paths.append(path)
    return [row["sample_id"] for row in pool], paths, plan["gains"]


def clap_embeddings(audio_paths: list[Path], batch_size: int, model_source: str,
                    revision: str | None) -> np.ndarray:
    try:
        import torch
        from scipy.signal import resample_poly
        from transformers import ClapAudioModelWithProjection, ClapProcessor
    except ImportError as error:
        raise RuntimeError("CLAP dependencies missing. Install the optional requirements in README.md first.") from error
    processor = ClapProcessor.from_pretrained(model_source, revision=revision)
    model = ClapAudioModelWithProjection.from_pretrained(model_source, revision=revision)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    batches = []
    for start in range(0, len(audio_paths), batch_size):
        audios = []
        for path in audio_paths[start:start + batch_size]:
            waveform, sample_rate = sf.read(path, dtype="float32")
            if sample_rate != 44100 or waveform.ndim != 1:
                raise ValueError(f"Unexpected CLAP input audio format: {path}")
            # Match the CLAP checkpoint's 48 kHz input contract.
            audios.append(resample_poly(waveform, 160, 147).astype(np.float32))
        inputs = processor(audios=audios, sampling_rate=48000, return_tensors="pt", padding=True)
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode():
            embeddings = model(**inputs).audio_embeds
        batches.append(embeddings.detach().cpu().numpy())
        print(f"CLAP embedded {min(start + len(audios), len(audio_paths)):,}/{len(audio_paths):,}")
    features = np.concatenate(batches, axis=0).astype(np.float32)
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    if np.any(norms == 0) or not np.isfinite(features).all():
        raise ValueError("CLAP returned invalid/zero embeddings")
    return features / norms


def get_embeddings(pool: list[dict[str, str]], cache_path: Path, meta_path: Path,
                   manifest_hash: str, seed: int, batch_size: int,
                   model_source: str, revision: str | None) -> tuple[np.ndarray, list[str], list[float]]:
    sample_ids = [row["sample_id"] for row in pool]
    if cache_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta.get("sample_ids") == sample_ids and meta.get("manifest_sha256") == manifest_hash
                and meta.get("seed") == seed and meta.get("model") == model_source
                and meta.get("revision") == revision):
            archive = np.load(cache_path, allow_pickle=False)
            return archive["embeddings"], sample_ids, meta["level_gains"]
    temp_parent = ROOT / "tmp"
    temp_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="c4_clap_", dir=temp_parent) as temp:
        _, audio_paths, gains = preprocess_pool(pool, Path(temp))
        embeddings = clap_embeddings(audio_paths, batch_size, model_source, revision)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, sample_ids=np.asarray(sample_ids), embeddings=embeddings)
    meta_path.write_text(json.dumps({"model": model_source, "revision": revision, "seed": seed,
                                     "manifest_sha256": manifest_hash,
                                     "sample_ids": sample_ids,
                                     "level_gains": gains,
                                     "embedding_dimension": int(embeddings.shape[1])}, indent=2) + "\n",
                         encoding="utf-8")
    return embeddings, sample_ids, gains


def build_triplets(pool: list[dict[str, str]], embeddings: np.ndarray,
                   seed: int, triplet_count: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows_by_id = {row["sample_id"]: row for row in pool}
    ids = [row["sample_id"] for row in pool]
    parameter_names = sorted({key.removesuffix("_sample_01") for key in pool[0]
                              if key.endswith("_sample_01")})
    params = np.stack([normalized_parameters(row, parameter_names) for row in pool])
    used: set[int] = set()
    anchors = list(range(len(ids)))
    rng.shuffle(anchors)
    result = []
    for anchor_idx in anchors:
        if len(result) == triplet_count:
            break
        if anchor_idx in used:
            continue
        similarities = embeddings @ embeddings[anchor_idx]
        ranked = np.argsort(-similarities)
        ranked = [int(i) for i in ranked if i != anchor_idx and int(i) not in used]
        if len(ranked) < 2:
            continue
        n = len(ranked)
        near_band = ranked[max(1, int(n * .05)):max(2, int(n * .20))]
        moderate_band = ranked[max(2, int(n * .20)):max(3, int(n * .40))]
        if not near_band or not moderate_band:
            continue
        candidate_near = rng.choice(near_band)
        candidate_moderate = rng.choice(moderate_band)
        if candidate_near in used or candidate_moderate in used:
            continue
        candidates = [candidate_near, candidate_moderate]
        rng.shuffle(candidates)
        used.update((anchor_idx, *candidates))
        triplet_number = len(result) + 1
        candidate_a, candidate_b = candidates
        result.append({
            "triplet_id": f"Q{triplet_number:02d}",
            "reference_sample_id": ids[anchor_idx],
            "candidate_a_sample_id": ids[candidate_a],
            "candidate_b_sample_id": ids[candidate_b],
            "clap_similarity_a": f"{float(similarities[candidate_a]):.8f}",
            "clap_similarity_b": f"{float(similarities[candidate_b]):.8f}",
            "clap_nearer_sample_id": ids[candidate_a if similarities[candidate_a] >= similarities[candidate_b] else candidate_b],
            "candidate_parameter_distance_a": f"{float(np.linalg.norm(params[anchor_idx]-params[candidate_a])/np.sqrt(params.shape[1])):.8f}",
            "candidate_parameter_distance_b": f"{float(np.linalg.norm(params[anchor_idx]-params[candidate_b])/np.sqrt(params.shape[1])):.8f}",
            "reference_raw_audio_path": rows_by_id[ids[anchor_idx]]["raw_audio_path"],
            "candidate_a_raw_audio_path": rows_by_id[ids[candidate_a]]["raw_audio_path"],
            "candidate_b_raw_audio_path": rows_by_id[ids[candidate_b]]["raw_audio_path"],
            "selection_method": "CLAP near-band versus moderately-near-band; both sampled without replacement",
        })
    if len(result) != triplet_count:
        raise ValueError(f"Could construct only {len(result)} of {triplet_count} unique triplets")
    return result


def simulate_responses(triplets: list[dict[str, str]], participants: int,
                       seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed + 1009)
    # Latent preferences are randomly assigned and independent from the CLAP ranking.
    preference = {t["triplet_id"]: rng.choice((t["candidate_a_sample_id"], t["candidate_b_sample_id"]))
                  for t in triplets}
    rows = []
    for person in range(1, participants + 1):
        participant = f"SYN_{person:03d}"
        consistency = rng.uniform(.58, .88)
        order = list(range(len(triplets)))
        rng.shuffle(order)
        for position, triplet_index in enumerate(order, start=1):
            triplet = triplets[triplet_index]
            favored = preference[triplet["triplet_id"]]
            candidate_a = triplet["candidate_a_sample_id"]
            candidate_b = triplet["candidate_b_sample_id"]
            if rng.random() < .5:
                candidate_a, candidate_b = candidate_b, candidate_a
            preferred_choice = "candidate_a" if candidate_a == favored else "candidate_b"
            choice = preferred_choice if rng.random() < consistency else ("candidate_b" if preferred_choice == "candidate_a" else "candidate_a")
            uncertain = rng.random() < .05
            if uncertain:
                choice = "cannot_decide"
            confidence = "" if uncertain else rng.choices([1, 2, 3, 4, 5], [5, 15, 30, 35, 15])[0]
            rows.append({
                "data_status": SYNTHETIC_MARK,
                "participant_id": participant,
                "question_id": triplet["triplet_id"],
                "trial_order": position,
                "reference_sample_id": triplet["reference_sample_id"],
                "candidate_a_sample_id": candidate_a,
                "candidate_b_sample_id": candidate_b,
                "choice": choice,
                "chosen_sample_id": None if uncertain else candidate_a if choice == "candidate_a" else candidate_b,
                "confidence_1_to_5": confidence,
                "comment": "",
                "synthetic_seed": seed,
            })
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_stimuli(triplets: list[dict[str, str]], manifest: list[dict[str, str]],
                   pool: list[dict[str, str]], pool_gains: list[float], output_dir: Path) -> dict[str, tuple[str, str]]:
    from generation.audio_processing import apply_level, dc_filter
    from generation.corpus_audio import read_raw

    ids = {sample_id for t in triplets for sample_id in (
        t["reference_sample_id"], t["candidate_a_sample_id"], t["candidate_b_sample_id"])}
    by_id = {row["sample_id"]: row for row in manifest}
    selected = [by_id[sample_id] for sample_id in sorted(ids)]
    audio = [dc_filter(read_raw(row, ROOT), 44100) for row in selected]
    gains_by_id = {row["sample_id"]: gain for row, gain in zip(pool, pool_gains)}
    output_dir.mkdir(parents=True, exist_ok=True)
    for row, signal in zip(selected, audio):
        gain = gains_by_id[row["sample_id"]]
        output = output_dir / f"{row['sample_id']}.wav"
        sf.write(output, apply_level(signal, gain, input_policy_id=row["audio_policy_id"]), 44100, subtype="PCM_16")
    expected = {row["sample_id"] for row in selected}
    for old_output in output_dir.glob("restricted_bend_sustain_v4_*.wav"):
        if old_output.stem not in expected:
            old_output.unlink()
    return {row["sample_id"]: (str((output_dir / f"{row['sample_id']}.wav").relative_to(ROOT)).replace("\\", "/"),
                                sha256(output_dir / f"{row['sample_id']}.wav")) for row in selected}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--expected-corpus-size", type=int, default=131072)
    parser.add_argument("--pool-size", type=int, default=1024)
    parser.add_argument("--participants", type=int, default=100)
    parser.add_argument("--triplets", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--model-path", type=Path, help="Optional local Hugging Face model directory")
    parser.add_argument("--model-revision", help="Optional pinned Hugging Face commit/revision")
    parser.add_argument("--responses-output", type=Path, default=OUTPUT_RESPONSES)
    parser.add_argument("--triplets-output", type=Path, default=OUTPUT_TRIPLETS)
    parser.add_argument("--cache", type=Path, default=OUTPUT_CACHE)
    args = parser.parse_args()
    if not 1 <= args.participants <= 100 or args.pool_size < args.triplets * 3:
        parser.error("participants must be 1-100 and pool-size must be at least three times triplets")

    manifest = load_manifest(args.manifest, args.expected_corpus_size)
    manifest_hash = sha256(args.manifest)
    rng = random.Random(args.seed)
    pool = rng.sample(manifest, args.pool_size)
    meta_path = args.cache.with_suffix(".json")
    model_source = str(args.model_path.resolve()) if args.model_path else MODEL_ID
    model_revision = args.model_revision or DEFAULT_MODEL_REVISION
    embeddings, _, pool_gains = get_embeddings(pool, args.cache, meta_path, manifest_hash,
                                               args.seed, args.batch_size, model_source, model_revision)
    triplets = build_triplets(pool, embeddings, args.seed, args.triplets)
    responses = simulate_responses(triplets, args.participants, args.seed)
    playback = export_stimuli(triplets, manifest, pool, pool_gains, STIMULI_DIR)
    for triplet in triplets:
        for role, sample_field in (("reference", "reference_sample_id"),
                                  ("candidate_a", "candidate_a_sample_id"),
                                  ("candidate_b", "candidate_b_sample_id")):
            path, digest = playback[triplet[sample_field]]
            triplet[f"{role}_playback_path"] = path
            triplet[f"{role}_playback_sha256"] = digest
    write_csv(args.triplets_output, triplets)
    write_csv(args.responses_output, responses)
    run_meta = {
        "data_status": SYNTHETIC_MARK,
        "corpus_manifest": str(args.manifest.relative_to(ROOT)),
        "corpus_manifest_sha256": manifest_hash,
        "full_corpus_size": args.expected_corpus_size,
        "clap_pool_size": args.pool_size,
        "triplets": args.triplets,
        "participants": args.participants,
        "rows": len(responses),
        "seed": args.seed,
        "clap_model": model_source,
        "clap_model_revision": model_revision,
        "human_preference_simulation_independent_of_clap": True,
    }
    (HERE / "generation_metadata.json").write_text(json.dumps(run_meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run_meta, indent=2))
    print("Synthetic responses are for software rehearsal only; never report as human results.")


if __name__ == "__main__":
    main()
