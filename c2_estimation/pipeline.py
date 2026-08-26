"""Deterministic Component 2 baseline for the canonical pilot_v1 dataset.

The pipeline validates the dataset, creates a reproducible split, extracts
fixed-reference log-mel spectrograms, trains a small CNN, and writes test-set
predictions and metrics. It intentionally contains no ensemble, uncertainty,
or Component 3 logic.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
import platform
import random
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "manifests" / "pilot_v1.csv"
DEFAULT_DATASET_CONFIG = PROJECT_ROOT / "data" / "manifests" / "pilot_v1_config.json"
DEFAULT_CACHE = PROJECT_ROOT / "data" / "processed" / "c2_pilot_v1_logmel.npz"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"

DEFAULT_SEED = 20260826
DEFAULT_N_FFT = 2048
DEFAULT_HOP_LENGTH = 512
DEFAULT_N_MELS = 64
DEFAULT_F_MIN = 20.0
DEFAULT_F_MAX = 20_000.0
DEFAULT_TOP_DB = 80.0


@dataclass(frozen=True)
class Sample:
    sample_id: str
    sample_index: int
    audio_path_text: str
    audio_path: Path
    targets: np.ndarray


class SpectrogramDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    def __init__(
        self,
        features: np.ndarray,
        targets: np.ndarray,
        indexes: np.ndarray,
    ) -> None:
        self.features = features
        self.targets = targets
        self.indexes = np.asarray(indexes, dtype=np.int64)

    def __len__(self) -> int:
        return len(self.indexes)

    def __getitem__(self, item: int) -> tuple[torch.Tensor, torch.Tensor]:
        index = int(self.indexes[item])
        feature = torch.from_numpy(self.features[index]).unsqueeze(0)
        target = torch.from_numpy(self.targets[index])
        return feature, target


class ParameterCNN(nn.Module):
    """Compact CNN whose outputs are normalized synthesizer parameters."""

    def __init__(self, target_minimums: np.ndarray, target_maximums: np.ndarray) -> None:
        super().__init__()
        output_count = len(target_minimums)
        self.features = nn.Sequential(
            nn.Conv2d(1, 8, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(8, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.AdaptiveAvgPool2d((2, 4)),
        )
        self.regressor = nn.Sequential(
            nn.Flatten(),
            nn.Linear(32 * 2 * 4, 64),
            nn.ReLU(),
            nn.Linear(64, output_count),
        )
        minimums = torch.as_tensor(target_minimums, dtype=torch.float32)
        ranges = torch.as_tensor(target_maximums - target_minimums, dtype=torch.float32)
        self.register_buffer("target_minimums", minimums)
        self.register_buffer("target_ranges", ranges)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        logits = self.regressor(self.features(inputs))
        return self.target_minimums + torch.sigmoid(logits) * self.target_ranges


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic C2 CNN baseline on pilot_v1."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dataset-config", type=Path, default=DEFAULT_DATASET_CONFIG)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=12)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument(
        "--force-preprocess",
        action="store_true",
        help="Recompute log-mel features even when the cache signature matches.",
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


def load_dataset(
    manifest_path: Path,
    config_path: Path,
) -> tuple[list[Sample], list[str], np.ndarray, np.ndarray, dict[str, Any]]:
    with config_path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)

    parameter_names = list(config["parameter_order"])
    if len(parameter_names) != 8:
        raise ValueError(
            f"C2 expects eight parameters; dataset config contains {len(parameter_names)}."
        )

    target_columns = [f"{name}_normalized" for name in parameter_names]
    target_minimums = np.asarray(
        [config["parameters"][name]["min"] for name in parameter_names],
        dtype=np.float32,
    )
    target_maximums = np.asarray(
        [config["parameters"][name]["max"] for name in parameter_names],
        dtype=np.float32,
    )
    if np.any(target_maximums <= target_minimums):
        raise ValueError("Every configured parameter maximum must exceed its minimum.")

    with manifest_path.open(newline="", encoding="utf-8-sig") as manifest_file:
        rows = list(csv.DictReader(manifest_file))
    expected_count = int(config["sample_count"])
    if len(rows) != expected_count:
        raise ValueError(
            f"Manifest has {len(rows)} rows; {config_path.name} declares {expected_count}."
        )

    samples: list[Sample] = []
    seen_ids: set[str] = set()
    seen_indexes: set[int] = set()
    expected_sample_rate = int(config["sample_rate"])
    expected_frames = round(expected_sample_rate * float(config["render_duration_seconds"]))

    for row in rows:
        missing = [column for column in target_columns if column not in row]
        if missing:
            raise ValueError(f"Manifest is missing target columns: {missing}")
        sample_id = row["sample_id"]
        sample_index = int(row["sample_index"])
        if sample_id in seen_ids or sample_index in seen_indexes:
            raise ValueError(f"Duplicate sample ID or index at {sample_id}.")
        seen_ids.add(sample_id)
        seen_indexes.add(sample_index)

        path_text = row["audio_path"]
        normalized_path = Path(path_text.replace("\\", "/"))
        audio_path = normalized_path if normalized_path.is_absolute() else PROJECT_ROOT / normalized_path
        if not audio_path.is_file():
            raise FileNotFoundError(f"Missing audio for {sample_id}: {audio_path}")
        info = sf.info(audio_path)
        if info.samplerate != expected_sample_rate or info.channels != 1 or info.frames != expected_frames:
            raise ValueError(
                f"Unexpected audio format for {sample_id}: "
                f"{info.samplerate} Hz, {info.channels} channel(s), {info.frames} frames."
            )

        targets = np.asarray([float(row[column]) for column in target_columns], dtype=np.float32)
        if not np.all(np.isfinite(targets)):
            raise ValueError(f"Non-finite target value in {sample_id}.")
        tolerance = 1e-6
        if np.any(targets < target_minimums - tolerance) or np.any(
            targets > target_maximums + tolerance
        ):
            raise ValueError(f"Target outside configured range in {sample_id}.")
        samples.append(Sample(sample_id, sample_index, path_text, audio_path, targets))

    samples.sort(key=lambda sample: sample.sample_index)
    if [sample.sample_index for sample in samples] != list(range(expected_count)):
        raise ValueError("Sample indexes must be contiguous from zero.")

    return samples, parameter_names, target_minimums, target_maximums, config


def deterministic_split(sample_count: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if sample_count < 10:
        raise ValueError("At least ten samples are required for an 80/10/10 split.")
    permutation = np.random.default_rng(seed).permutation(sample_count)
    train_count = int(sample_count * 0.8)
    validation_count = int(sample_count * 0.1)
    train_indexes = np.sort(permutation[:train_count])
    validation_indexes = np.sort(permutation[train_count : train_count + validation_count])
    test_indexes = np.sort(permutation[train_count + validation_count :])
    return train_indexes, validation_indexes, test_indexes


def save_split_manifest(
    path: Path,
    samples: list[Sample],
    parameter_names: list[str],
    train_indexes: np.ndarray,
    validation_indexes: np.ndarray,
    test_indexes: np.ndarray,
) -> str:
    split_by_index = np.empty(len(samples), dtype=object)
    split_by_index[train_indexes] = "train"
    split_by_index[validation_indexes] = "validation"
    split_by_index[test_indexes] = "test"
    fieldnames = ["sample_id", "sample_index", "audio_path", "split"] + [
        f"{name}_normalized" for name in parameter_names
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for index, sample in enumerate(samples):
            row: dict[str, str | int | float] = {
                "sample_id": sample.sample_id,
                "sample_index": sample.sample_index,
                "audio_path": sample.audio_path_text,
                "split": str(split_by_index[index]),
            }
            row.update(
                {
                    f"{name}_normalized": float(value)
                    for name, value in zip(parameter_names, sample.targets, strict=True)
                }
            )
            writer.writerow(row)
    assignment = "\n".join(
        f"{sample.sample_id},{split_by_index[index]}" for index, sample in enumerate(samples)
    )
    return hashlib.sha256(assignment.encode("utf-8")).hexdigest()


def hz_to_mel(frequency_hz: np.ndarray | float) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + np.asarray(frequency_hz) / 700.0)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def create_mel_filterbank(
    sample_rate: int,
    n_fft: int,
    n_mels: int,
    f_min: float,
    f_max: float,
) -> np.ndarray:
    if not 0.0 <= f_min < f_max <= sample_rate / 2.0:
        raise ValueError("Mel frequency limits must be inside the Nyquist interval.")
    frequencies = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    mel_points = np.linspace(hz_to_mel(f_min), hz_to_mel(f_max), n_mels + 2)
    hz_points = mel_to_hz(mel_points)
    bank = np.zeros((n_mels, len(frequencies)), dtype=np.float32)
    for index in range(n_mels):
        left, center, right = hz_points[index : index + 3]
        rising = (frequencies - left) / max(center - left, np.finfo(float).eps)
        falling = (right - frequencies) / max(right - center, np.finfo(float).eps)
        bank[index] = np.maximum(0.0, np.minimum(rising, falling))
    if np.any(bank.sum(axis=1) == 0.0):
        raise ValueError("At least one mel filter is empty; adjust FFT or mel settings.")
    return bank


def extract_log_mel(
    audio: np.ndarray,
    window: np.ndarray,
    mel_filterbank: np.ndarray,
    n_fft: int,
    hop_length: int,
    top_db: float,
) -> np.ndarray:
    padded = np.pad(audio.astype(np.float32, copy=False), n_fft // 2, mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop_length]
    spectrum = np.fft.rfft(frames * window, n=n_fft, axis=1)
    amplitude = np.abs(spectrum) / max(float(window.sum() / 2.0), np.finfo(float).eps)
    power = np.square(amplitude)
    mel_power = power @ mel_filterbank.T
    log_mel_db = 10.0 * np.log10(np.maximum(mel_power, 1e-10))
    log_mel_db = np.clip(log_mel_db, -top_db, 0.0)
    return np.ascontiguousarray(log_mel_db.T, dtype=np.float32)


def preprocessing_settings(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_rate": int(config["sample_rate"]),
        "n_fft": DEFAULT_N_FFT,
        "hop_length": DEFAULT_HOP_LENGTH,
        "n_mels": DEFAULT_N_MELS,
        "f_min_hz": DEFAULT_F_MIN,
        "f_max_hz": DEFAULT_F_MAX,
        "top_db": DEFAULT_TOP_DB,
        "center_padding": "reflect",
        "window": "Hann",
        "spectrum": "power",
        "decibel_reference": "fixed 0 dBFS",
    }


def feature_cache_signature(
    manifest_sha256: str,
    sample_ids: Iterable[str],
    settings: dict[str, Any],
) -> str:
    value = {
        "manifest_sha256": manifest_sha256,
        "sample_ids": list(sample_ids),
        "preprocessing": settings,
    }
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_or_extract_features(
    samples: list[Sample],
    cache_path: Path,
    cache_signature: str,
    settings: dict[str, Any],
    force: bool,
) -> tuple[np.ndarray, bool]:
    if cache_path.is_file() and not force:
        with np.load(cache_path, allow_pickle=False) as cache:
            cached_signature = str(cache["signature"].item())
            features = cache["features"]
            cached_ids = cache["sample_ids"].astype(str).tolist()
        if cached_signature == cache_signature and cached_ids == [s.sample_id for s in samples]:
            print(f"Using matching feature cache: {relative_path(cache_path)}")
            return np.ascontiguousarray(features, dtype=np.float32), True
        print("Feature cache signature does not match; recomputing.")

    sample_rate = int(settings["sample_rate"])
    n_fft = int(settings["n_fft"])
    hop_length = int(settings["hop_length"])
    window = np.hanning(n_fft).astype(np.float32)
    mel_filterbank = create_mel_filterbank(
        sample_rate,
        n_fft,
        int(settings["n_mels"]),
        float(settings["f_min_hz"]),
        float(settings["f_max_hz"]),
    )
    extracted: list[np.ndarray] = []
    print(f"Extracting log-mel spectrograms for {len(samples)} files...")
    for position, sample in enumerate(samples, start=1):
        audio, actual_sample_rate = sf.read(sample.audio_path, dtype="float32", always_2d=False)
        if actual_sample_rate != sample_rate or audio.ndim != 1:
            raise ValueError(f"Unexpected audio while reading {sample.sample_id}.")
        extracted.append(
            extract_log_mel(
                audio,
                window,
                mel_filterbank,
                n_fft,
                hop_length,
                float(settings["top_db"]),
            )
        )
        if position == 1 or position % 64 == 0 or position == len(samples):
            print(f"  [{position:>4}/{len(samples)}] {sample.sample_id}")

    features = np.stack(extracted).astype(np.float32, copy=False)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_cache = cache_path.with_suffix(".tmp.npz")
    np.savez(
        temporary_cache,
        features=features,
        sample_ids=np.asarray([sample.sample_id for sample in samples]),
        signature=np.asarray(cache_signature),
    )
    temporary_cache.replace(cache_path)
    print(f"Saved feature cache: {relative_path(cache_path)}")
    return features, False


def save_spectrogram_examples(
    output_dir: Path,
    features_db: np.ndarray,
    samples: list[Sample],
    split_names: np.ndarray,
    settings: dict[str, Any],
) -> list[str]:
    example_dir = output_dir / "spectrogram_examples"
    example_dir.mkdir(parents=True, exist_ok=True)
    indexes = np.linspace(0, len(samples) - 1, num=4, dtype=int)
    duration = float(features_db.shape[2] * int(settings["hop_length"])) / float(
        settings["sample_rate"]
    )
    saved_paths: list[str] = []
    for index in indexes:
        sample = samples[int(index)]
        figure, axis = plt.subplots(figsize=(10, 4.2), constrained_layout=True)
        image = axis.imshow(
            features_db[int(index)],
            origin="lower",
            aspect="auto",
            extent=(0.0, duration, 0, int(settings["n_mels"])),
            cmap="magma",
            vmin=-float(settings["top_db"]),
            vmax=0.0,
        )
        axis.set_title(f"{sample.sample_id} ({split_names[int(index)]})")
        axis.set_xlabel("Time (seconds)")
        axis.set_ylabel(
            f"Mel band ({float(settings['f_min_hz']):g} Hz–"
            f"{float(settings['f_max_hz']) / 1000:g} kHz)"
        )
        colorbar = figure.colorbar(image, ax=axis)
        colorbar.set_label("Power (dBFS)")
        output_path = example_dir / f"{sample.sample_id}.png"
        figure.savefig(output_path, dpi=150)
        plt.close(figure)
        saved_paths.append(relative_path(output_path))
    return saved_paths


def set_deterministic_execution(seed: int, threads: int) -> None:
    if threads <= 0:
        raise ValueError("--threads must be positive.")
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available.")
    return torch.device(requested)


def normalized_range_mse(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    target_ranges: torch.Tensor,
) -> torch.Tensor:
    return torch.mean(torch.square((predictions - targets) / target_ranges))


def evaluate_loss(
    model: nn.Module,
    loader: DataLoader[tuple[torch.Tensor, torch.Tensor]],
    device: torch.device,
    target_ranges: torch.Tensor,
) -> float:
    model.eval()
    total_loss = 0.0
    total_count = 0
    with torch.no_grad():
        for features, targets in loader:
            features = features.to(device)
            targets = targets.to(device)
            loss = normalized_range_mse(model(features), targets, target_ranges)
            total_loss += float(loss.item()) * len(features)
            total_count += len(features)
    return total_loss / total_count


def train_model(
    model: ParameterCNN,
    train_loader: DataLoader[tuple[torch.Tensor, torch.Tensor]],
    validation_loader: DataLoader[tuple[torch.Tensor, torch.Tensor]],
    device: torch.device,
    epochs: int,
    learning_rate: float,
    weight_decay: float,
    patience: int,
) -> tuple[list[dict[str, float | int]], int, float]:
    if epochs <= 0 or patience <= 0:
        raise ValueError("--epochs and --patience must be positive.")
    model.to(device)
    target_ranges = model.target_ranges.to(device)
    optimizer = torch.optim.Adam(
        model.parameters(), learning_rate, weight_decay=weight_decay
    )
    history: list[dict[str, float | int]] = []
    best_state = copy.deepcopy(model.state_dict())
    best_validation_loss = math.inf
    best_epoch = 0
    stale_epochs = 0

    print(f"Training on {device.type}...")
    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        total_count = 0
        for features, targets in train_loader:
            features = features.to(device)
            targets = targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            predictions = model(features)
            loss = normalized_range_mse(predictions, targets, target_ranges)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(features)
            total_count += len(features)

        train_loss = total_loss / total_count
        validation_loss = evaluate_loss(model, validation_loader, device, target_ranges)
        history.append(
            {
                "epoch": epoch,
                "train_normalized_mse": train_loss,
                "validation_normalized_mse": validation_loss,
            }
        )
        print(
            f"  epoch {epoch:>3}/{epochs}: train={train_loss:.6f}, "
            f"validation={validation_loss:.6f}"
        )
        if validation_loss < best_validation_loss:
            best_validation_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= patience:
                print(f"  early stopping after {epoch} epochs")
                break

    model.load_state_dict(best_state)
    return history, best_epoch, best_validation_loss


def predict(
    model: ParameterCNN,
    loader: DataLoader[tuple[torch.Tensor, torch.Tensor]],
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    prediction_batches: list[np.ndarray] = []
    target_batches: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for features, targets in loader:
            predictions = model(features.to(device)).cpu().numpy()
            prediction_batches.append(predictions)
            target_batches.append(targets.numpy())
    return np.concatenate(prediction_batches), np.concatenate(target_batches)


def calculate_metrics(
    predictions: np.ndarray,
    targets: np.ndarray,
    parameter_names: list[str],
) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for index, parameter in enumerate(parameter_names):
        residual = predictions[:, index] - targets[:, index]
        mae = float(np.mean(np.abs(residual)))
        rmse = float(np.sqrt(np.mean(np.square(residual))))
        centered = targets[:, index] - np.mean(targets[:, index])
        denominator = float(np.sum(np.square(centered)))
        r_squared = 1.0 - float(np.sum(np.square(residual))) / denominator
        rows.append(
            {
                "parameter": parameter,
                "test_samples": len(targets),
                "mae": mae,
                "rmse": rmse,
                "r_squared": r_squared,
            }
        )
    return rows


def save_history(path: Path, history: list[dict[str, float | int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)


def save_loss_plot(path: Path, history: list[dict[str, float | int]]) -> None:
    epochs = [int(row["epoch"]) for row in history]
    train_loss = [float(row["train_normalized_mse"]) for row in history]
    validation_loss = [float(row["validation_normalized_mse"]) for row in history]
    figure, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    axis.plot(epochs, train_loss, label="Train")
    axis.plot(epochs, validation_loss, label="Validation")
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Range-normalized MSE")
    axis.set_title("C2 pilot_v1 CNN learning curves")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def save_metrics(
    csv_path: Path,
    json_path: Path,
    metric_rows: list[dict[str, float | int | str]],
) -> dict[str, float]:
    with csv_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(metric_rows[0]))
        writer.writeheader()
        writer.writerows(metric_rows)
    macro_average = {
        "mae": float(np.mean([float(row["mae"]) for row in metric_rows])),
        "rmse": float(np.mean([float(row["rmse"]) for row in metric_rows])),
        "r_squared": float(
            np.mean([float(row["r_squared"]) for row in metric_rows])
        ),
    }
    write_json(
        json_path,
        {"per_parameter": metric_rows, "macro_average": macro_average},
    )
    return macro_average


def save_predictions(
    path: Path,
    test_indexes: np.ndarray,
    samples: list[Sample],
    parameter_names: list[str],
    predictions: np.ndarray,
    targets: np.ndarray,
) -> None:
    fieldnames = ["sample_id", "sample_index"]
    for parameter in parameter_names:
        fieldnames.extend(
            [f"{parameter}_actual", f"{parameter}_predicted", f"{parameter}_error"]
        )
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for row_index, sample_index in enumerate(test_indexes):
            sample = samples[int(sample_index)]
            row: dict[str, str | int | float] = {
                "sample_id": sample.sample_id,
                "sample_index": sample.sample_index,
            }
            for parameter_index, parameter in enumerate(parameter_names):
                actual = float(targets[row_index, parameter_index])
                predicted = float(predictions[row_index, parameter_index])
                row[f"{parameter}_actual"] = actual
                row[f"{parameter}_predicted"] = predicted
                row[f"{parameter}_error"] = predicted - actual
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    config_path = args.dataset_config.resolve()
    cache_path = args.cache.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    set_deterministic_execution(args.seed, args.threads)
    device = choose_device(args.device)
    samples, parameter_names, target_minimums, target_maximums, dataset_config = load_dataset(
        manifest_path, config_path
    )
    targets = np.stack([sample.targets for sample in samples]).astype(np.float32)
    train_indexes, validation_indexes, test_indexes = deterministic_split(
        len(samples), args.seed
    )
    split_names = np.empty(len(samples), dtype=object)
    split_names[train_indexes] = "train"
    split_names[validation_indexes] = "validation"
    split_names[test_indexes] = "test"
    split_hash = save_split_manifest(
        output_dir / "split_manifest.csv",
        samples,
        parameter_names,
        train_indexes,
        validation_indexes,
        test_indexes,
    )
    print(
        f"Validated {len(samples)} samples; split counts are "
        f"{len(train_indexes)}/{len(validation_indexes)}/{len(test_indexes)}."
    )

    manifest_hash = sha256_file(manifest_path)
    preprocessing = preprocessing_settings(dataset_config)
    cache_signature = feature_cache_signature(
        manifest_hash, (sample.sample_id for sample in samples), preprocessing
    )
    features_db, cache_was_reused = load_or_extract_features(
        samples,
        cache_path,
        cache_signature,
        preprocessing,
        args.force_preprocess,
    )
    expected_shape = (
        len(samples),
        int(preprocessing["n_mels"]),
        1
        + (
            round(
                float(dataset_config["render_duration_seconds"])
                * int(preprocessing["sample_rate"])
            )
            // int(preprocessing["hop_length"])
        ),
    )
    if features_db.shape != expected_shape:
        raise ValueError(
            f"Unexpected feature shape {features_db.shape}; expected {expected_shape}."
        )
    example_paths = save_spectrogram_examples(
        output_dir, features_db, samples, split_names, preprocessing
    )

    input_mean = float(features_db[train_indexes].mean(dtype=np.float64))
    input_std = float(features_db[train_indexes].std(dtype=np.float64))
    if not math.isfinite(input_std) or input_std <= 0.0:
        raise ValueError("Training features have invalid standard deviation.")
    features = np.ascontiguousarray((features_db - input_mean) / input_std, dtype=np.float32)

    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(
        SpectrogramDataset(features, targets, train_indexes),
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        generator=generator,
    )
    validation_loader = DataLoader(
        SpectrogramDataset(features, targets, validation_indexes),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )
    test_loader = DataLoader(
        SpectrogramDataset(features, targets, test_indexes),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )

    model = ParameterCNN(target_minimums, target_maximums)
    history, best_epoch, best_validation_loss = train_model(
        model,
        train_loader,
        validation_loader,
        device,
        args.epochs,
        args.learning_rate,
        args.weight_decay,
        args.patience,
    )
    model_path = output_dir / "best_model.pt"
    torch.save(
        {
            "model_state_dict": model.cpu().state_dict(),
            "parameter_names": parameter_names,
            "target_minimums": target_minimums.tolist(),
            "target_maximums": target_maximums.tolist(),
            "input_mean_db": input_mean,
            "input_std_db": input_std,
            "preprocessing": preprocessing,
            "split_seed": args.seed,
            "best_epoch": best_epoch,
        },
        model_path,
    )
    model.to(device)
    predictions, test_targets = predict(model, test_loader, device)
    metric_rows = calculate_metrics(predictions, test_targets, parameter_names)

    history_path = output_dir / "training_history.csv"
    save_history(history_path, history)
    save_loss_plot(output_dir / "learning_curves.png", history)
    macro_average = save_metrics(
        output_dir / "test_metrics.csv",
        output_dir / "test_metrics.json",
        metric_rows,
    )
    save_predictions(
        output_dir / "test_predictions.csv",
        test_indexes,
        samples,
        parameter_names,
        predictions,
        test_targets,
    )

    model_parameters = sum(parameter.numel() for parameter in model.parameters())
    run_config = {
        "scope": "Component 2 deterministic single-CNN baseline only",
        "dataset": {
            "name": "pilot_v1",
            "manifest": relative_path(manifest_path),
            "manifest_sha256": manifest_hash,
            "dataset_config": relative_path(config_path),
            "sample_count": len(samples),
        },
        "split": {
            "method": "NumPy default_rng seeded permutation; floor 80%, floor 10%, remainder 10%",
            "seed": args.seed,
            "train_count": len(train_indexes),
            "validation_count": len(validation_indexes),
            "test_count": len(test_indexes),
            "assignment_sha256": split_hash,
        },
        "preprocessing": {
            **preprocessing,
            "feature_shape": list(features_db.shape[1:]),
            "training_split_mean_db": input_mean,
            "training_split_std_db": input_std,
            "cache": relative_path(cache_path),
            "cache_signature": cache_signature,
            "cache_reused_for_this_run": cache_was_reused,
            "spectrogram_examples": example_paths,
        },
        "model": {
            "class": "ParameterCNN",
            "trainable_parameters": model_parameters,
            "output": "sigmoid mapped to each configured normalized synthesizer range",
            "targets": parameter_names,
        },
        "training": {
            "device": str(device),
            "deterministic_algorithms": True,
            "threads": args.threads,
            "maximum_epochs": args.epochs,
            "epochs_completed": len(history),
            "best_epoch": best_epoch,
            "best_validation_normalized_mse": best_validation_loss,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
            "early_stopping_patience": args.patience,
        },
        "test_macro_average": macro_average,
        "versions": {
            "python": platform.python_version(),
            "numpy": version("numpy"),
            "soundfile": version("soundfile"),
            "matplotlib": version("matplotlib"),
            "torch": version("torch"),
        },
    }
    write_json(output_dir / "run_config.json", run_config)

    print("\nTest metrics (normalized synthesizer parameter units):")
    print(f"{'parameter':<20} {'MAE':>10} {'RMSE':>10} {'R^2':>10}")
    for row in metric_rows:
        print(
            f"{str(row['parameter']):<20} {float(row['mae']):>10.5f} "
            f"{float(row['rmse']):>10.5f} {float(row['r_squared']):>10.5f}"
        )
    print(f"\nSaved C2 outputs to {relative_path(output_dir)}")


if __name__ == "__main__":
    main()
