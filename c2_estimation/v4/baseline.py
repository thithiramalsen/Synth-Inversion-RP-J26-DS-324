"""Train a reproducible 13-output baseline; evaluate inverse-validation ONLY."""
from __future__ import annotations

import os
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import argparse
import json
from pathlib import Path
import platform
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset

from c2_estimation.pipeline import ParameterCNN, choose_device, set_deterministic_execution
from c2_estimation.v4.data import (DEFAULT_PREPARED, NAMES, ROOT, SEED, digest_json,
                                  load_prepared, sha, write_json)
from c2_estimation.v4.features import SHARD_SIZE, load_cache, training_statistics


class CachedDataset(Dataset):
    def __init__(self, arrays, targets, indexes, mean, std):
        self.arrays, self.targets, self.indexes = arrays, targets, indexes
        self.mean, self.std = mean, std

    def __len__(self):
        return len(self.indexes)

    def __getitem__(self, item):
        index = int(self.indexes[item])
        feature = np.array(self.arrays[index // SHARD_SIZE][index % SHARD_SIZE], copy=True)
        feature -= self.mean
        feature /= self.std
        return torch.from_numpy(feature[None]), torch.from_numpy(np.array(self.targets[index], copy=True))


def regression_metrics(predicted, actual, lower, upper) -> list[dict]:
    rows = []
    for coordinate, pred, truth in (
        ("research_z", predicted, actual),
        ("vital_normalized", lower + predicted * (upper-lower), lower + actual * (upper-lower)),
    ):
        for j, name in enumerate(NAMES):
            error = pred[:, j].astype(np.float64) - truth[:, j]
            denominator = float(np.square(truth[:, j] - truth[:, j].mean()).sum())
            rows.append({"parameter": name, "coordinate": coordinate, "count": len(truth),
                         "mae": float(np.abs(error).mean()), "rmse": float(np.sqrt(np.square(error).mean())),
                         "r_squared": 1 - float(np.square(error).sum()) / denominator if denominator > 0 else None})
    return rows


def evaluate(model, loader, device):
    model.eval()
    predictions, targets = [], []
    with torch.no_grad():
        for x, y in loader:
            predictions.append(model(x.to(device)).cpu().numpy())
            targets.append(y.numpy())
    return np.concatenate(predictions), np.concatenate(targets)


def atomic_checkpoint(path, state):
    temporary = path.with_suffix(".pt.tmp")
    torch.save(state, temporary)
    temporary.replace(path)


def save_examples(output, arrays, frame, indexes):
    folder = output / "spectrogram_examples"
    folder.mkdir(exist_ok=True)
    for index in indexes[:4]:
        row = frame.iloc[index]
        values = arrays[index // SHARD_SIZE][index % SHARD_SIZE]
        fig, ax = plt.subplots(figsize=(8, 3.5), constrained_layout=True)
        image = ax.imshow(values, origin="lower", aspect="auto", extent=(0, 3, 0, 64),
                          cmap="magma", vmin=-80, vmax=0)
        ax.set(title=f"{row.sample_id} | train", xlabel="Time (seconds)", ylabel="Mel band")
        fig.colorbar(image, ax=ax, label="Log-mel power (fixed-reference dB)")
        fig.savefig(folder / f"{row.sample_id}.png", dpi=120)
        plt.close(fig)


def train(args):
    if min(args.epochs, args.batch_size, args.patience, args.threads) <= 0:
        raise ValueError("Epochs, batch size, patience and threads must be positive")
    set_deterministic_execution(args.seed, args.threads)
    device = choose_device(args.device)
    protocol, _ = load_prepared(args.prepared)
    cache, frame, arrays = load_cache(args.cache)
    if cache["protocol_sha256"] != sha(args.prepared / "protocol.json"):
        raise ValueError("Cache belongs to a different frozen protocol")
    if not ((frame.split == "train") | ((frame.split == "validation") & (frame.validation_role == "inverse"))).all():
        raise ValueError("Baseline must not consume calibration, reliability-validation or test data")
    train_indexes = np.flatnonzero(frame.split.to_numpy() == "train")
    val_indexes = np.flatnonzero(frame.split.to_numpy() == "validation")
    mean, std = training_statistics(arrays, train_indexes)
    targets = frame[[n + "_z" for n in NAMES]].to_numpy(dtype=np.float32)
    config = {"cache_signature": cache["signature"], "protocol_sha256": cache["protocol_sha256"],
              "scope": cache["scope"], "seed": args.seed, "batch_size": args.batch_size,
              "learning_rate": args.learning_rate, "weight_decay": args.weight_decay,
              "epochs": args.epochs, "patience": args.patience, "threads": args.threads,
              "device": str(device), "feature_mean_train_only": mean, "feature_std_train_only": std,
              "train_count": len(train_indexes), "validation_count": len(val_indexes),
              "evaluation_partition": "validation/inverse", "test_evaluated": False,
              "parameter_names": list(NAMES), "lower": protocol["lower"], "upper": protocol["upper"],
              "python": platform.python_version(), "torch": str(torch.__version__),
              "numpy": np.__version__, "cuda": torch.version.cuda,
              "sources": {name: sha(ROOT / name) for name in (
                  "c2_estimation/v4/baseline.py", "c2_estimation/v4/features.py",
                  "c2_estimation/v4/data.py", "c2_estimation/pipeline.py")}}
    signature = digest_json(config)
    if args.output.exists() and any(args.output.iterdir()):
        if not args.resume:
            raise ValueError("Existing run: specify --resume with identical settings or use a new output")
        saved = json.loads((args.output / "run_config.json").read_text(encoding="utf-8"))
        if saved["signature"] != signature:
            raise ValueError("Resume configuration/source differs")
    else:
        if args.resume:
            raise ValueError("No run to resume")
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / "run_config.json", {"signature": signature, **config})
    train_data = CachedDataset(arrays, targets, train_indexes, mean, std)
    val_loader = DataLoader(CachedDataset(arrays, targets, val_indexes, mean, std),
                            batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = ParameterCNN(np.zeros(13, dtype=np.float32), np.ones(13, dtype=np.float32)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    history, best, stale, first_epoch = [], float("inf"), 0, 1
    if args.resume:
        last = torch.load(args.output / "last_model.pt", map_location=device, weights_only=True)
        model.load_state_dict(last["model"])
        optimizer.load_state_dict(last["optimizer"])
        history, best, stale, first_epoch = last["history"], last["best"], last["stale"], last["epoch"] + 1
    start = time.perf_counter()
    for epoch in range(first_epoch, args.epochs + 1):
        if stale >= args.patience:
            break
        # Epoch-addressable shuffle makes resumed runs reproduce uninterrupted runs.
        shuffle = torch.Generator().manual_seed(args.seed + epoch)
        loader = DataLoader(train_data, batch_size=args.batch_size, shuffle=True,
                            generator=shuffle, num_workers=0)
        model.train()
        loss_total = 0.
        for x, y in loader:
            optimizer.zero_grad(set_to_none=True)
            prediction = model(x.to(device))
            loss = torch.mean(torch.square(prediction - y.to(device)))
            if not torch.isfinite(loss):
                raise ValueError("Non-finite training loss")
            loss.backward()
            optimizer.step()
            loss_total += float(loss.detach().cpu()) * len(x)
        pred, truth = evaluate(model, val_loader, device)
        validation_loss = float(np.square(pred.astype(np.float64) - truth).mean())
        row = {"epoch": epoch, "train_z_mse": loss_total / len(train_data), "validation_z_mse": validation_loss}
        history.append(row)
        if validation_loss < best:
            best, stale = validation_loss, 0
            atomic_checkpoint(args.output / "best_model.pt", {"model": model.state_dict(),
                "epoch": epoch, "config": config, "signature": signature})
        else:
            stale += 1
        atomic_checkpoint(args.output / "last_model.pt", {"model": model.state_dict(),
            "optimizer": optimizer.state_dict(), "history": history, "best": best,
            "stale": stale, "epoch": epoch, "signature": signature})
        pd.DataFrame(history).to_csv(args.output / "training_history.csv", index=False)
        print(f"Epoch {epoch}/{args.epochs}: train={row['train_z_mse']:.6f} validation={validation_loss:.6f}; elapsed={time.perf_counter()-start:.1f}s", flush=True)
    saved = torch.load(args.output / "best_model.pt", map_location=device, weights_only=True)
    model.load_state_dict(saved["model"])
    predictions, truth = evaluate(model, val_loader, device)
    # Training is float32; reported truth retains the actual float64 engine readbacks.
    truth = frame.iloc[val_indexes][[n + "_z" for n in NAMES]].to_numpy(dtype=np.float64)
    lower, upper = np.array(protocol["lower"]), np.array(protocol["upper"])
    metrics = regression_metrics(predictions, truth, lower, upper)
    pd.DataFrame(metrics).to_csv(args.output / "validation_metrics.csv", index=False)
    mean_prediction = np.broadcast_to(targets[train_indexes].mean(axis=0), truth.shape)
    mean_metrics = regression_metrics(mean_prediction, truth, lower, upper)
    pd.DataFrame(mean_metrics).to_csv(args.output / "mean_baseline_metrics.csv", index=False)
    records = frame.iloc[val_indexes][["sample_id", "sample_index", "split", "validation_role"]].copy()
    for j, name in enumerate(NAMES):
        records[name + "_true_z"] = truth[:, j]
        records[name + "_predicted_z"] = predictions[:, j].astype(np.float64)
        records[name + "_true_vital"] = lower[j] + truth[:, j] * (upper[j]-lower[j])
        records[name + "_predicted_vital"] = lower[j] + predictions[:, j].astype(np.float64) * (upper[j]-lower[j])
    records.to_csv(args.output / "validation_predictions.csv", index=False)
    # Independent checkpoint load must reproduce the delivered predictions.
    reloaded = ParameterCNN(np.zeros(13, dtype=np.float32), np.ones(13, dtype=np.float32)).to(device)
    reloaded.load_state_dict(torch.load(args.output / "best_model.pt", map_location=device, weights_only=True)["model"])
    reloaded_predictions, _ = evaluate(reloaded, val_loader, device)
    if not np.array_equal(predictions, reloaded_predictions):
        raise ValueError("Checkpoint reload did not reproduce predictions")
    save_examples(args.output, arrays, frame, train_indexes)
    fig, ax = plt.subplots(figsize=(7, 4), constrained_layout=True)
    ax.plot([h["epoch"] for h in history], [h["train_z_mse"] for h in history], label="Train")
    ax.plot([h["epoch"] for h in history], [h["validation_z_mse"] for h in history], label="Inverse validation")
    ax.set(xlabel="Epoch", ylabel="Research-range MSE")
    ax.legend()
    fig.savefig(args.output / "learning_curves.png", dpi=120)
    plt.close(fig)
    summary = {"status": "completed_development_sanity_run" if cache["scope"] == "development" else "completed_deterministic_baseline",
               "best_epoch": saved["epoch"], "validation_z_mse": best,
               "mean_baseline_z_mse": float(np.square(mean_prediction.astype(np.float64)-truth).mean()),
               "macro_validation_z_mae": float(np.abs(predictions.astype(np.float64)-truth).mean()),
               "checkpoint_reload_exact": True, "test_evaluated": False,
               "checkpoint_sha256": sha(args.output / "best_model.pt"),
               "predictions_sha256": sha(args.output / "validation_predictions.csv"),
               "uncertainty_calibration_implemented": False}
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=.001)
    parser.add_argument("--weight-decay", type=float, default=.0001)
    parser.add_argument("--patience", type=int, default=6)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--resume", action="store_true")
    train(parser.parse_args())
