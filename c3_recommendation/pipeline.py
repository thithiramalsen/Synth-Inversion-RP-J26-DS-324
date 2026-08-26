"""Component 3 audio retrieval and parameter-space MMR prototype.

The required retrieval signal is audio similarity. Parameter values are used
only to rerank the audio-retrieved candidate pool for diversity. C2 outputs,
DPP selection, text descriptors, and user-preference signals are intentionally
outside this prototype.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "manifests" / "pilot_v1.csv"
DEFAULT_DATASET_CONFIG = PROJECT_ROOT / "data" / "manifests" / "pilot_v1_config.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"

DEFAULT_SEED = 20260826
DEFAULT_TOP_K = 5
DEFAULT_RETRIEVAL_POOL_SIZE = 50
DEFAULT_MMR_LAMBDA = 0.75
DEFAULT_EVALUATION_QUERIES = 32
LAMBDA_SWEEP = (0.50, 0.60, 0.70, 0.75, 0.80, 0.90, 1.00)

DEFAULT_N_FFT = 2048
DEFAULT_HOP_LENGTH = 512
DEFAULT_N_MELS = 40
DEFAULT_N_MFCC = 13
DEFAULT_F_MIN = 20.0
DEFAULT_F_MAX = 20_000.0


@dataclass(frozen=True)
class CandidatePatch:
    sample_id: str
    sample_index: int
    audio_path_text: str
    audio_path: Path
    parameters: np.ndarray


@dataclass(frozen=True)
class RetrievalResult:
    candidate_index: int
    audio_rank: int
    audio_similarity: float
    mmr_score: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the C3 MFCC retrieval and parameter-space MMR prototype."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dataset-config", type=Path, default=DEFAULT_DATASET_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--retrieval-pool-size", type=int, default=DEFAULT_RETRIEVAL_POOL_SIZE
    )
    parser.add_argument("--mmr-lambda", type=float, default=DEFAULT_MMR_LAMBDA)
    parser.add_argument(
        "--evaluation-queries", type=int, default=DEFAULT_EVALUATION_QUERIES
    )
    parser.add_argument(
        "--query-audio",
        type=Path,
        help="Optional isolated target audio clip. Runs one external query instead of evaluation.",
    )
    parser.add_argument(
        "--query-id",
        help="Optional pilot_v1 sample ID for an inspectable single-query run.",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Recompute the candidate MFCC database even when its signature matches.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(value, output_file, indent=2, sort_keys=True)
        output_file.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_candidates(
    manifest_path: Path,
    config_path: Path,
) -> tuple[list[CandidatePatch], list[str], np.ndarray, np.ndarray, dict[str, Any]]:
    with config_path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    parameter_names = list(config["parameter_order"])
    if len(parameter_names) != 8:
        raise ValueError(f"C3 expects eight parameters; found {len(parameter_names)}.")
    parameter_columns = [f"{name}_normalized" for name in parameter_names]
    parameter_minimums = np.asarray(
        [config["parameters"][name]["min"] for name in parameter_names],
        dtype=np.float64,
    )
    parameter_maximums = np.asarray(
        [config["parameters"][name]["max"] for name in parameter_names],
        dtype=np.float64,
    )

    with manifest_path.open(newline="", encoding="utf-8-sig") as manifest_file:
        rows = list(csv.DictReader(manifest_file))
    expected_count = int(config["sample_count"])
    if len(rows) != expected_count:
        raise ValueError(
            f"Manifest contains {len(rows)} rows; dataset config declares {expected_count}."
        )

    candidates: list[CandidatePatch] = []
    seen_ids: set[str] = set()
    for row in rows:
        sample_id = row["sample_id"]
        if sample_id in seen_ids:
            raise ValueError(f"Duplicate candidate ID: {sample_id}")
        seen_ids.add(sample_id)
        path_text = row["audio_path"]
        normalized_path = Path(path_text.replace("\\", "/"))
        audio_path = normalized_path if normalized_path.is_absolute() else PROJECT_ROOT / normalized_path
        if not audio_path.is_file():
            raise FileNotFoundError(f"Missing candidate audio for {sample_id}: {audio_path}")
        parameters = np.asarray(
            [float(row[column]) for column in parameter_columns], dtype=np.float64
        )
        tolerance = 1e-6
        if np.any(parameters < parameter_minimums - tolerance) or np.any(
            parameters > parameter_maximums + tolerance
        ):
            raise ValueError(f"Parameter outside configured range in {sample_id}.")
        candidates.append(
            CandidatePatch(
                sample_id=sample_id,
                sample_index=int(row["sample_index"]),
                audio_path_text=path_text,
                audio_path=audio_path,
                parameters=parameters,
            )
        )
    candidates.sort(key=lambda candidate: candidate.sample_index)
    if [candidate.sample_index for candidate in candidates] != list(range(expected_count)):
        raise ValueError("Candidate sample indexes must be contiguous from zero.")
    return candidates, parameter_names, parameter_minimums, parameter_maximums, config


def feature_settings(dataset_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_rate": int(dataset_config["sample_rate"]),
        "n_fft": DEFAULT_N_FFT,
        "hop_length": DEFAULT_HOP_LENGTH,
        "n_mels": DEFAULT_N_MELS,
        "n_mfcc": DEFAULT_N_MFCC,
        "f_min_hz": DEFAULT_F_MIN,
        "f_max_hz": DEFAULT_F_MAX,
        "window": "Hann",
        "frame_padding": "reflect",
        "summary": "per-coefficient mean and standard deviation",
    }


def feature_names(n_mfcc: int) -> list[str]:
    return [f"mfcc_{index:02d}_mean" for index in range(1, n_mfcc + 1)] + [
        f"mfcc_{index:02d}_std" for index in range(1, n_mfcc + 1)
    ]


def hz_to_mel(frequency_hz: np.ndarray | float) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + np.asarray(frequency_hz) / 700.0)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def mel_filterbank(
    sample_rate: int,
    n_fft: int,
    n_mels: int,
    f_min_hz: float,
    f_max_hz: float,
) -> np.ndarray:
    if not 0.0 <= f_min_hz < f_max_hz <= sample_rate / 2.0:
        raise ValueError("MFCC frequency limits must be inside the Nyquist interval.")
    frequencies = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    points_hz = mel_to_hz(
        np.linspace(hz_to_mel(f_min_hz), hz_to_mel(f_max_hz), n_mels + 2)
    )
    bank = np.zeros((n_mels, len(frequencies)), dtype=np.float64)
    for index in range(n_mels):
        left, center, right = points_hz[index : index + 3]
        rising = (frequencies - left) / max(center - left, np.finfo(float).eps)
        falling = (right - frequencies) / max(right - center, np.finfo(float).eps)
        bank[index] = np.maximum(0.0, np.minimum(rising, falling))
    if np.any(bank.sum(axis=1) == 0.0):
        raise ValueError("At least one mel filter is empty.")
    return bank


def dct_basis(n_mfcc: int, n_mels: int) -> np.ndarray:
    mel_indexes = np.arange(n_mels, dtype=np.float64)
    coefficient_indexes = np.arange(n_mfcc, dtype=np.float64)[:, None]
    basis = np.cos(np.pi / n_mels * (mel_indexes + 0.5) * coefficient_indexes)
    basis[0] *= math.sqrt(1.0 / n_mels)
    basis[1:] *= math.sqrt(2.0 / n_mels)
    return basis


def read_target_audio(path: Path, target_sample_rate: int) -> np.ndarray:
    audio, sample_rate = sf.read(path, dtype="float64", always_2d=True)
    if len(audio) == 0:
        raise ValueError(f"Audio clip is empty: {path}")
    mono = audio.mean(axis=1)
    if sample_rate != target_sample_rate:
        divisor = math.gcd(sample_rate, target_sample_rate)
        mono = resample_poly(
            mono,
            target_sample_rate // divisor,
            sample_rate // divisor,
        )
    return np.asarray(mono, dtype=np.float64)


def extract_mfcc_summary(
    audio: np.ndarray,
    settings: dict[str, Any],
    bank: np.ndarray | None = None,
    basis: np.ndarray | None = None,
) -> np.ndarray:
    n_fft = int(settings["n_fft"])
    hop_length = int(settings["hop_length"])
    if len(audio) == 1:
        audio = np.pad(audio, (0, 1), mode="constant")
    pad_mode = "reflect" if len(audio) > 1 else "constant"
    padded = np.pad(audio, n_fft // 2, mode=pad_mode)
    if len(padded) < n_fft:
        padded = np.pad(padded, (0, n_fft - len(padded)))
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop_length]
    window = np.hanning(n_fft)
    spectrum = np.fft.rfft(frames * window, n=n_fft, axis=1)
    power = np.square(np.abs(spectrum) / max(window.sum() / 2.0, np.finfo(float).eps))
    if bank is None:
        bank = mel_filterbank(
            int(settings["sample_rate"]),
            n_fft,
            int(settings["n_mels"]),
            float(settings["f_min_hz"]),
            float(settings["f_max_hz"]),
        )
    if basis is None:
        basis = dct_basis(int(settings["n_mfcc"]), int(settings["n_mels"]))
    log_mel = np.log(np.maximum(power @ bank.T, 1e-12))
    mfcc = log_mel @ basis.T
    return np.concatenate((mfcc.mean(axis=0), mfcc.std(axis=0)))


def database_signature(
    manifest_sha256: str,
    sample_ids: Iterable[str],
    settings: dict[str, Any],
) -> str:
    payload = json.dumps(
        {
            "manifest_sha256": manifest_sha256,
            "sample_ids": list(sample_ids),
            "feature_settings": settings,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_candidate_database(
    path: Path,
    candidates: list[CandidatePatch],
    parameter_names: list[str],
    features: np.ndarray,
    names: list[str],
) -> None:
    fieldnames = ["sample_id", "sample_index", "audio_path"] + [
        f"{name}_normalized" for name in parameter_names
    ] + names
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        row: dict[str, Any] = {
            "sample_id": candidate.sample_id,
            "sample_index": candidate.sample_index,
            "audio_path": candidate.audio_path_text,
        }
        row.update(
            {
                f"{name}_normalized": float(value)
                for name, value in zip(
                    parameter_names, candidate.parameters, strict=True
                )
            }
        )
        row.update(
            {name: float(value) for name, value in zip(names, features[index], strict=True)}
        )
        rows.append(row)
    write_csv(path, rows, fieldnames)


def load_candidate_features(path: Path, names: list[str]) -> np.ndarray:
    with path.open(newline="", encoding="utf-8-sig") as input_file:
        rows = list(csv.DictReader(input_file))
    return np.asarray(
        [[float(row[name]) for name in names] for row in rows], dtype=np.float64
    )


def build_or_load_database(
    candidates: list[CandidatePatch],
    parameter_names: list[str],
    output_dir: Path,
    manifest_hash: str,
    settings: dict[str, Any],
    force_rebuild: bool,
) -> tuple[np.ndarray, str, bool]:
    database_path = output_dir / "candidate_patch_database.csv"
    metadata_path = output_dir / "candidate_patch_database_metadata.json"
    signature = database_signature(
        manifest_hash, (candidate.sample_id for candidate in candidates), settings
    )
    names = feature_names(int(settings["n_mfcc"]))
    if database_path.is_file() and metadata_path.is_file() and not force_rebuild:
        with metadata_path.open(encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
        if metadata.get("database_signature") == signature:
            features = load_candidate_features(database_path, names)
            if features.shape == (len(candidates), len(names)):
                print(f"Using matching candidate database: {relative_path(database_path)}")
                return features, signature, True
        print("Candidate database signature does not match; rebuilding.")

    bank = mel_filterbank(
        int(settings["sample_rate"]),
        int(settings["n_fft"]),
        int(settings["n_mels"]),
        float(settings["f_min_hz"]),
        float(settings["f_max_hz"]),
    )
    basis = dct_basis(int(settings["n_mfcc"]), int(settings["n_mels"]))
    feature_rows: list[np.ndarray] = []
    print(f"Building MFCC candidate database from {len(candidates)} pilot_v1 patches...")
    for position, candidate in enumerate(candidates, start=1):
        audio = read_target_audio(candidate.audio_path, int(settings["sample_rate"]))
        feature_rows.append(extract_mfcc_summary(audio, settings, bank, basis))
        if position == 1 or position % 64 == 0 or position == len(candidates):
            print(f"  [{position:>4}/{len(candidates)}] {candidate.sample_id}")
    features = np.stack(feature_rows)
    save_candidate_database(
        database_path, candidates, parameter_names, features, names
    )
    write_json(
        metadata_path,
        {
            "candidate_count": len(candidates),
            "database_signature": signature,
            "feature_columns": names,
            "feature_settings": settings,
            "manifest_sha256": manifest_hash,
            "scope": "MFCC audio features and normalized pilot_v1 parameters",
        },
    )
    print(f"Saved candidate database: {relative_path(database_path)}")
    return features, signature, False


def standardize_audio_features(
    features: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = features.mean(axis=0)
    standard_deviation = features.std(axis=0)
    standard_deviation[standard_deviation < 1e-12] = 1.0
    standardized = (features - mean) / standard_deviation
    norms = np.linalg.norm(standardized, axis=1, keepdims=True)
    if np.any(norms <= 0.0):
        raise ValueError("At least one candidate has a zero standardized MFCC vector.")
    return standardized / norms, mean, standard_deviation


def standardize_query(
    query_feature: np.ndarray,
    mean: np.ndarray,
    standard_deviation: np.ndarray,
) -> np.ndarray:
    standardized = (query_feature - mean) / standard_deviation
    norm = float(np.linalg.norm(standardized))
    if norm <= 0.0:
        raise ValueError("Query has a zero standardized MFCC vector.")
    return standardized / norm


def normalized_parameter_matrix(
    candidates: list[CandidatePatch],
    minimums: np.ndarray,
    maximums: np.ndarray,
) -> np.ndarray:
    parameters = np.stack([candidate.parameters for candidate in candidates])
    return (parameters - minimums) / (maximums - minimums)


def parameter_distance(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.linalg.norm(first - second) / math.sqrt(len(first)))


def audio_ranked_pool(
    query_unit_feature: np.ndarray,
    candidate_unit_features: np.ndarray,
    candidates: list[CandidatePatch],
    pool_size: int,
    excluded_index: int | None,
) -> tuple[np.ndarray, np.ndarray]:
    similarities = candidate_unit_features @ query_unit_feature
    eligible = np.ones(len(candidates), dtype=bool)
    if excluded_index is not None:
        eligible[excluded_index] = False
    eligible_indexes = np.flatnonzero(eligible)
    ordered_positions = np.lexsort(
        (
            np.asarray([candidates[index].sample_index for index in eligible_indexes]),
            -similarities[eligible_indexes],
        )
    )
    ranked_indexes = eligible_indexes[ordered_positions]
    pool_indexes = ranked_indexes[:pool_size]
    return pool_indexes, similarities[pool_indexes]


def baseline_results(
    pool_indexes: np.ndarray,
    pool_similarities: np.ndarray,
    top_k: int,
) -> list[RetrievalResult]:
    return [
        RetrievalResult(
            candidate_index=int(pool_indexes[position]),
            audio_rank=position + 1,
            audio_similarity=float(pool_similarities[position]),
            mmr_score=None,
        )
        for position in range(top_k)
    ]


def mmr_results(
    pool_indexes: np.ndarray,
    pool_similarities: np.ndarray,
    normalized_parameters: np.ndarray,
    top_k: int,
    mmr_lambda: float,
) -> list[RetrievalResult]:
    if not 0.0 <= mmr_lambda <= 1.0:
        raise ValueError("MMR lambda must be between zero and one.")
    selected_positions: list[int] = []
    remaining_positions = list(range(len(pool_indexes)))
    while len(selected_positions) < top_k:
        best_position: int | None = None
        best_key: tuple[float, float, int] | None = None
        best_score = -math.inf
        for position in remaining_positions:
            relevance = (float(pool_similarities[position]) + 1.0) / 2.0
            if not selected_positions:
                redundancy = 0.0
            else:
                candidate_parameters = normalized_parameters[int(pool_indexes[position])]
                redundancy = max(
                    1.0
                    - parameter_distance(
                        candidate_parameters,
                        normalized_parameters[int(pool_indexes[selected_position])],
                    )
                    for selected_position in selected_positions
                )
            score = mmr_lambda * relevance - (1.0 - mmr_lambda) * redundancy
            tie_key = (
                score,
                float(pool_similarities[position]),
                -int(pool_indexes[position]),
            )
            if best_key is None or tie_key > best_key:
                best_key = tie_key
                best_position = position
                best_score = score
        if best_position is None:
            raise RuntimeError("MMR could not select a candidate.")
        selected_positions.append(best_position)
        remaining_positions.remove(best_position)
    return [
        RetrievalResult(
            candidate_index=int(pool_indexes[position]),
            audio_rank=position + 1,
            audio_similarity=float(pool_similarities[position]),
            mmr_score=mmr_lambda
            * (float(pool_similarities[position]) + 1.0)
            / 2.0
            if rank == 0
            else compute_mmr_score_at_selection(
                position,
                selected_positions[:rank],
                pool_indexes,
                pool_similarities,
                normalized_parameters,
                mmr_lambda,
            ),
        )
        for rank, position in enumerate(selected_positions)
    ]


def compute_mmr_score_at_selection(
    position: int,
    previous_positions: list[int],
    pool_indexes: np.ndarray,
    pool_similarities: np.ndarray,
    normalized_parameters: np.ndarray,
    mmr_lambda: float,
) -> float:
    relevance = (float(pool_similarities[position]) + 1.0) / 2.0
    candidate_parameters = normalized_parameters[int(pool_indexes[position])]
    redundancy = max(
        1.0
        - parameter_distance(
            candidate_parameters,
            normalized_parameters[int(pool_indexes[previous])],
        )
        for previous in previous_positions
    )
    return mmr_lambda * relevance - (1.0 - mmr_lambda) * redundancy


def recommendation_metrics(
    results: list[RetrievalResult],
    normalized_parameters: np.ndarray,
    query_parameters: np.ndarray | None,
) -> dict[str, float]:
    similarities = np.asarray([result.audio_similarity for result in results])
    pairwise_distances = [
        parameter_distance(
            normalized_parameters[results[first].candidate_index],
            normalized_parameters[results[second].candidate_index],
        )
        for first in range(len(results))
        for second in range(first + 1, len(results))
    ]
    metrics = {
        "mean_audio_similarity": float(similarities.mean()),
        "minimum_audio_similarity": float(similarities.min()),
        "mean_pairwise_parameter_distance": float(np.mean(pairwise_distances)),
        "minimum_pairwise_parameter_distance": float(np.min(pairwise_distances)),
    }
    if query_parameters is not None:
        metrics["mean_query_parameter_distance"] = float(
            np.mean(
                [
                    parameter_distance(
                        query_parameters,
                        normalized_parameters[result.candidate_index],
                    )
                    for result in results
                ]
            )
        )
    return metrics


def recommendation_rows(
    query_id: str,
    query_audio_path: str,
    method: str,
    results: list[RetrievalResult],
    candidates: list[CandidatePatch],
    parameter_names: list[str],
    normalized_parameters: np.ndarray,
    query_parameters: np.ndarray | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, result in enumerate(results, start=1):
        candidate = candidates[result.candidate_index]
        row: dict[str, Any] = {
            "query_id": query_id,
            "query_audio_path": query_audio_path,
            "method": method,
            "recommendation_rank": rank,
            "candidate_sample_id": candidate.sample_id,
            "candidate_audio_path": candidate.audio_path_text,
            "candidate_audio_rank": result.audio_rank,
            "audio_cosine_similarity": result.audio_similarity,
            "mmr_score": "" if result.mmr_score is None else result.mmr_score,
            "query_parameter_distance": ""
            if query_parameters is None
            else parameter_distance(
                query_parameters, normalized_parameters[result.candidate_index]
            ),
        }
        row.update(
            {
                f"{name}_normalized": float(value)
                for name, value in zip(
                    parameter_names, candidate.parameters, strict=True
                )
            }
        )
        rows.append(row)
    return rows


def recommendation_fieldnames(parameter_names: list[str]) -> list[str]:
    return [
        "query_id",
        "query_audio_path",
        "method",
        "recommendation_rank",
        "candidate_sample_id",
        "candidate_audio_path",
        "candidate_audio_rank",
        "audio_cosine_similarity",
        "mmr_score",
        "query_parameter_distance",
    ] + [f"{name}_normalized" for name in parameter_names]


def aggregate_metrics(rows: list[dict[str, Any]], prefix: str) -> dict[str, float]:
    keys = [
        "mean_audio_similarity",
        "minimum_audio_similarity",
        "mean_pairwise_parameter_distance",
        "minimum_pairwise_parameter_distance",
        "mean_query_parameter_distance",
    ]
    return {
        f"{prefix}_{key}": float(np.mean([float(row[f"{prefix}_{key}"]) for row in rows]))
        for key in keys
    }


def choose_evaluation_indexes(
    candidate_count: int,
    query_count: int,
    seed: int,
) -> np.ndarray:
    if not 0 < query_count < candidate_count:
        raise ValueError("Evaluation query count must be between 1 and candidate count - 1.")
    return np.sort(
        np.random.default_rng(seed).choice(
            candidate_count, size=query_count, replace=False
        )
    )


def save_tradeoff_plot(path: Path, sweep_rows: list[dict[str, Any]]) -> None:
    audio = [float(row["mean_audio_similarity"]) for row in sweep_rows]
    diversity = [float(row["mean_pairwise_parameter_distance"]) for row in sweep_rows]
    lambdas = [float(row["mmr_lambda"]) for row in sweep_rows]
    figure, axis = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
    axis.plot(diversity, audio, color="#1b6a55", linewidth=2, alpha=0.75)
    scatter = axis.scatter(diversity, audio, c=lambdas, cmap="viridis", s=90, zorder=3)
    for x_value, y_value, lambda_value in zip(diversity, audio, lambdas, strict=True):
        axis.annotate(
            f"λ={lambda_value:.2f}",
            (x_value, y_value),
            xytext=(7, 5),
            textcoords="offset points",
            fontsize=9,
        )
    axis.set_xlabel("Mean pairwise parameter distance (higher = more diverse)")
    axis.set_ylabel("Mean MFCC cosine similarity (higher = more relevant)")
    axis.set_title("C3 audio relevance vs parameter diversity")
    axis.grid(alpha=0.25)
    colorbar = figure.colorbar(scatter, ax=axis)
    colorbar.set_label("MMR λ (audio-relevance weight)")
    figure.savefig(path, dpi=150)
    plt.close(figure)


def run_evaluation(
    output_dir: Path,
    candidates: list[CandidatePatch],
    parameter_names: list[str],
    candidate_unit_features: np.ndarray,
    normalized_parameters: np.ndarray,
    evaluation_indexes: np.ndarray,
    top_k: int,
    pool_size: int,
    mmr_lambda: float,
) -> dict[str, Any]:
    baseline_rows: list[dict[str, Any]] = []
    mmr_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    query_manifest_rows: list[dict[str, Any]] = []
    pools: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    for query_index in evaluation_indexes:
        query_index = int(query_index)
        query = candidates[query_index]
        query_parameters = normalized_parameters[query_index]
        pool_indexes, pool_similarities = audio_ranked_pool(
            candidate_unit_features[query_index],
            candidate_unit_features,
            candidates,
            pool_size,
            query_index,
        )
        pools[query_index] = (pool_indexes, pool_similarities)
        baseline = baseline_results(pool_indexes, pool_similarities, top_k)
        reranked = mmr_results(
            pool_indexes,
            pool_similarities,
            normalized_parameters,
            top_k,
            mmr_lambda,
        )
        baseline_metric = recommendation_metrics(
            baseline, normalized_parameters, query_parameters
        )
        mmr_metric = recommendation_metrics(reranked, normalized_parameters, query_parameters)
        comparison_rows.append(
            {
                "query_id": query.sample_id,
                **{f"baseline_{key}": value for key, value in baseline_metric.items()},
                **{f"mmr_{key}": value for key, value in mmr_metric.items()},
            }
        )
        query_manifest_rows.append(
            {
                "query_id": query.sample_id,
                "sample_index": query.sample_index,
                "audio_path": query.audio_path_text,
            }
        )
        baseline_rows.extend(
            recommendation_rows(
                query.sample_id,
                query.audio_path_text,
                "audio_top_k",
                baseline,
                candidates,
                parameter_names,
                normalized_parameters,
                query_parameters,
            )
        )
        mmr_rows.extend(
            recommendation_rows(
                query.sample_id,
                query.audio_path_text,
                "audio_top_k_parameter_mmr",
                reranked,
                candidates,
                parameter_names,
                normalized_parameters,
                query_parameters,
            )
        )

    write_csv(
        output_dir / "evaluation_queries.csv",
        query_manifest_rows,
        ["query_id", "sample_index", "audio_path"],
    )
    result_fields = recommendation_fieldnames(parameter_names)
    write_csv(
        output_dir / "baseline_recommendations.csv", baseline_rows, result_fields
    )
    write_csv(output_dir / "mmr_recommendations.csv", mmr_rows, result_fields)
    comparison_fields = ["query_id"] + [
        f"{prefix}_{key}"
        for prefix in ("baseline", "mmr")
        for key in (
            "mean_audio_similarity",
            "minimum_audio_similarity",
            "mean_pairwise_parameter_distance",
            "minimum_pairwise_parameter_distance",
            "mean_query_parameter_distance",
        )
    ]
    write_csv(
        output_dir / "query_comparison.csv", comparison_rows, comparison_fields
    )

    baseline_aggregate = aggregate_metrics(comparison_rows, "baseline")
    mmr_aggregate = aggregate_metrics(comparison_rows, "mmr")
    sweep_rows: list[dict[str, Any]] = []
    for lambda_value in LAMBDA_SWEEP:
        metrics: list[dict[str, float]] = []
        for query_index in evaluation_indexes:
            query_index = int(query_index)
            pool_indexes, pool_similarities = pools[query_index]
            selected = mmr_results(
                pool_indexes,
                pool_similarities,
                normalized_parameters,
                top_k,
                lambda_value,
            )
            metrics.append(
                recommendation_metrics(
                    selected,
                    normalized_parameters,
                    normalized_parameters[query_index],
                )
            )
        sweep_rows.append(
            {
                "mmr_lambda": lambda_value,
                **{
                    key: float(np.mean([metric[key] for metric in metrics]))
                    for key in metrics[0]
                },
            }
        )
    write_csv(
        output_dir / "lambda_sweep.csv",
        sweep_rows,
        list(sweep_rows[0]),
    )
    save_tradeoff_plot(output_dir / "audio_parameter_tradeoff.png", sweep_rows)

    summary = {
        "evaluation_query_count": len(evaluation_indexes),
        "top_k": top_k,
        "retrieval_pool_size": pool_size,
        "mmr_lambda": mmr_lambda,
        "baseline": baseline_aggregate,
        "parameter_mmr": mmr_aggregate,
        "change": {
            "mean_audio_similarity": mmr_aggregate["mmr_mean_audio_similarity"]
            - baseline_aggregate["baseline_mean_audio_similarity"],
            "mean_pairwise_parameter_distance": mmr_aggregate[
                "mmr_mean_pairwise_parameter_distance"
            ]
            - baseline_aggregate["baseline_mean_pairwise_parameter_distance"],
            "minimum_pairwise_parameter_distance": mmr_aggregate[
                "mmr_minimum_pairwise_parameter_distance"
            ]
            - baseline_aggregate["baseline_minimum_pairwise_parameter_distance"],
        },
    }
    write_json(output_dir / "comparison_summary.json", summary)
    return summary


def safe_query_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return normalized or "query"


def run_single_query(
    output_dir: Path,
    query_id: str,
    query_audio_path: Path,
    query_feature: np.ndarray,
    query_parameters: np.ndarray | None,
    excluded_index: int | None,
    candidates: list[CandidatePatch],
    parameter_names: list[str],
    candidate_unit_features: np.ndarray,
    normalized_parameters: np.ndarray,
    feature_mean: np.ndarray,
    feature_standard_deviation: np.ndarray,
    top_k: int,
    pool_size: int,
    mmr_lambda: float,
) -> dict[str, Any]:
    query_unit = standardize_query(
        query_feature, feature_mean, feature_standard_deviation
    )
    pool_indexes, pool_similarities = audio_ranked_pool(
        query_unit,
        candidate_unit_features,
        candidates,
        pool_size,
        excluded_index,
    )
    baseline = baseline_results(pool_indexes, pool_similarities, top_k)
    reranked = mmr_results(
        pool_indexes,
        pool_similarities,
        normalized_parameters,
        top_k,
        mmr_lambda,
    )
    query_run_dir = output_dir / "query_runs" / safe_query_name(query_id)
    fields = recommendation_fieldnames(parameter_names)
    write_csv(
        query_run_dir / "baseline_recommendations.csv",
        recommendation_rows(
            query_id,
            relative_path(query_audio_path),
            "audio_top_k",
            baseline,
            candidates,
            parameter_names,
            normalized_parameters,
            query_parameters,
        ),
        fields,
    )
    write_csv(
        query_run_dir / "mmr_recommendations.csv",
        recommendation_rows(
            query_id,
            relative_path(query_audio_path),
            "audio_top_k_parameter_mmr",
            reranked,
            candidates,
            parameter_names,
            normalized_parameters,
            query_parameters,
        ),
        fields,
    )
    summary = {
        "query_id": query_id,
        "query_audio_path": relative_path(query_audio_path),
        "top_k": top_k,
        "retrieval_pool_size": pool_size,
        "mmr_lambda": mmr_lambda,
        "baseline": recommendation_metrics(
            baseline, normalized_parameters, query_parameters
        ),
        "parameter_mmr": recommendation_metrics(
            reranked, normalized_parameters, query_parameters
        ),
    }
    write_json(query_run_dir / "summary.json", summary)
    print(f"Saved single-query recommendations to {relative_path(query_run_dir)}")
    return summary


def validate_retrieval_arguments(
    candidate_count: int,
    top_k: int,
    pool_size: int,
    mmr_lambda: float,
) -> None:
    if top_k < 2:
        raise ValueError("--top-k must be at least two to measure diversity.")
    if pool_size < top_k:
        raise ValueError("--retrieval-pool-size must be at least --top-k.")
    if pool_size >= candidate_count:
        raise ValueError("--retrieval-pool-size must be smaller than candidate count.")
    if not 0.0 <= mmr_lambda <= 1.0:
        raise ValueError("--mmr-lambda must be between zero and one.")


def main() -> None:
    args = parse_args()
    if args.query_audio is not None and args.query_id is not None:
        raise ValueError("Use either --query-audio or --query-id, not both.")
    manifest_path = args.manifest.resolve()
    config_path = args.dataset_config.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates, parameter_names, parameter_minimums, parameter_maximums, config = (
        load_candidates(manifest_path, config_path)
    )
    validate_retrieval_arguments(
        len(candidates), args.top_k, args.retrieval_pool_size, args.mmr_lambda
    )
    settings = feature_settings(config)
    manifest_hash = sha256_file(manifest_path)
    features, signature, database_reused = build_or_load_database(
        candidates,
        parameter_names,
        output_dir,
        manifest_hash,
        settings,
        args.force_rebuild,
    )
    candidate_unit_features, feature_mean, feature_standard_deviation = (
        standardize_audio_features(features)
    )
    normalized_parameters = normalized_parameter_matrix(
        candidates, parameter_minimums, parameter_maximums
    )

    if args.query_audio is not None:
        query_audio_path = args.query_audio.resolve()
        if not query_audio_path.is_file():
            raise FileNotFoundError(f"Query audio was not found: {query_audio_path}")
        query_audio = read_target_audio(query_audio_path, int(settings["sample_rate"]))
        query_feature = extract_mfcc_summary(query_audio, settings)
        result = run_single_query(
            output_dir,
            query_audio_path.stem,
            query_audio_path,
            query_feature,
            None,
            None,
            candidates,
            parameter_names,
            candidate_unit_features,
            normalized_parameters,
            feature_mean,
            feature_standard_deviation,
            args.top_k,
            args.retrieval_pool_size,
            args.mmr_lambda,
        )
        mode = "external_query"
    elif args.query_id is not None:
        indexes_by_id = {
            candidate.sample_id: index for index, candidate in enumerate(candidates)
        }
        if args.query_id not in indexes_by_id:
            raise ValueError(f"Unknown pilot_v1 query ID: {args.query_id}")
        query_index = indexes_by_id[args.query_id]
        query = candidates[query_index]
        result = run_single_query(
            output_dir,
            query.sample_id,
            query.audio_path,
            features[query_index],
            normalized_parameters[query_index],
            query_index,
            candidates,
            parameter_names,
            candidate_unit_features,
            normalized_parameters,
            feature_mean,
            feature_standard_deviation,
            args.top_k,
            args.retrieval_pool_size,
            args.mmr_lambda,
        )
        mode = "pilot_query"
    else:
        evaluation_indexes = choose_evaluation_indexes(
            len(candidates), args.evaluation_queries, args.seed
        )
        result = run_evaluation(
            output_dir,
            candidates,
            parameter_names,
            candidate_unit_features,
            normalized_parameters,
            evaluation_indexes,
            args.top_k,
            args.retrieval_pool_size,
            args.mmr_lambda,
        )
        mode = "seeded_evaluation"

    run_config = {
        "scope": {
            "component": "C3",
            "input": "isolated synthesizer audio",
            "baseline": "MFCC cosine-similarity top-k retrieval",
            "reranking": "parameter-space maximal marginal relevance",
            "excluded": [
                "C2 predictions or uncertainty",
                "timbre-description input",
                "determinantal point processes",
                "user-preference evaluation",
            ],
        },
        "mode": mode,
        "dataset": {
            "name": "pilot_v1",
            "candidate_count": len(candidates),
            "manifest": relative_path(manifest_path),
            "manifest_sha256": manifest_hash,
            "dataset_config": relative_path(config_path),
        },
        "candidate_database": {
            "path": relative_path(output_dir / "candidate_patch_database.csv"),
            "database_signature": signature,
            "reused_for_this_run": database_reused,
            "feature_settings": settings,
            "feature_standardization_mean": feature_mean.tolist(),
            "feature_standardization_std": feature_standard_deviation.tolist(),
        },
        "retrieval": {
            "seed": args.seed,
            "top_k": args.top_k,
            "retrieval_pool_size": args.retrieval_pool_size,
            "mmr_lambda": args.mmr_lambda,
            "evaluation_queries": args.evaluation_queries,
            "parameter_distance": "Euclidean after scaling each parameter to its configured pilot range, divided by sqrt(8)",
        },
        "result": result,
        "versions": {
            "numpy": version("numpy"),
            "scipy": version("scipy"),
            "soundfile": version("soundfile"),
            "matplotlib": version("matplotlib"),
        },
    }
    write_json(output_dir / "run_config.json", run_config)

    if mode == "seeded_evaluation":
        baseline = result["baseline"]
        reranked = result["parameter_mmr"]
        print("\nC3 evaluation aggregate:")
        print(
            "  audio top-k:  "
            f"similarity={baseline['baseline_mean_audio_similarity']:.5f}, "
            f"parameter diversity={baseline['baseline_mean_pairwise_parameter_distance']:.5f}"
        )
        print(
            "  MMR reranked: "
            f"similarity={reranked['mmr_mean_audio_similarity']:.5f}, "
            f"parameter diversity={reranked['mmr_mean_pairwise_parameter_distance']:.5f}"
        )
        print(f"Saved C3 outputs to {relative_path(output_dir)}")


if __name__ == "__main__":
    main()
