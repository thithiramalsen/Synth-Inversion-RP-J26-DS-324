"""Independent Gaussian-head CNNs; frozen point estimates and variance components.

Variance is an uncertainty feature, NOT a calibrated correctness probability.
Only training and inverse-validation rows enter training/model selection.
"""
from __future__ import annotations

import os
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from c2_estimation.pipeline import choose_device, set_deterministic_execution
from c2_estimation.v4.baseline import CachedDataset, atomic_checkpoint, build_model, regression_metrics
from c2_estimation.v4.data import DEFAULT_PREPARED, NAMES, ROOT, SEED, digest_json, load_prepared, sha, write_json
from c2_estimation.v4.features import load_cache, training_statistics


class GaussianCNN(nn.Module):
    def __init__(self, device, variance_floor=1e-4):
        super().__init__()
        if not 0 < variance_floor < .05:
            raise ValueError("Variance floor must be in (0, .05)")
        base = build_model(device)
        self.features = base.features
        self.shared = nn.Sequential(*list(base.regressor.children())[:-1])
        self.mean_head = nn.Linear(64, 13)
        self.variance_head = nn.Linear(64, 13)
        # Start near the variance of a moderately informative bounded regressor.
        nn.init.zeros_(self.variance_head.weight)
        nn.init.constant_(self.variance_head.bias, float(np.log(np.expm1(.05-variance_floor))))
        self.variance_floor = variance_floor

    def forward(self, x):
        hidden = self.shared(self.features(x))
        mean = torch.sigmoid(self.mean_head(hidden))
        variance = torch.nn.functional.softplus(self.variance_head(hidden)) + self.variance_floor
        return mean, variance


def gaussian_nll(mean, variance, target):
    return .5 * (torch.log(variance) + (mean-target).square()/variance).mean()


def combine(means, variances):
    """Equal-weight mixture moments; population (ddof=0) between-member variance."""
    means, variances = np.asarray(means, dtype=np.float64), np.asarray(variances, dtype=np.float64)
    if means.ndim != 3 or means.shape != variances.shape or means.shape[-1] != 13:
        raise ValueError("Expected member x sample x 13 matching moments")
    if not np.isfinite(means).all() or not np.isfinite(variances).all() or (variances <= 0).any():
        raise ValueError("Invalid probabilistic predictions")
    mean = means.mean(axis=0)
    within = variances.mean(axis=0)
    between = np.square(means-mean).mean(axis=0)
    return mean, within, between, within+between


def evaluate(model, loader, device):
    model.eval()
    means, variances = [], []
    with torch.no_grad():
        for x, _ in loader:
            mean, variance = model(x.to(device))
            means.append(mean.cpu().numpy())
            variances.append(variance.cpu().numpy())
    return np.concatenate(means), np.concatenate(variances)


def prediction_frame(frame, means, variances, lower, upper):
    mean, within, between, total = combine(means, variances)
    result = frame[["sample_id", "sample_index", "split", "validation_role", "diagnostic_rank"]].copy()
    truth = frame[[n+"_z" for n in NAMES]].to_numpy(dtype=np.float64)
    for j, name in enumerate(NAMES):
        for suffix, values in (("actual_z", truth), ("predicted_z", mean),
                               ("within_variance_z", within), ("between_variance_z", between),
                               ("total_variance_z", total)):
            result[name+"_"+suffix] = values[:, j]
        result[name+"_predicted_normalized"] = lower[j]+mean[:, j]*(upper[j]-lower[j])
    return result


def train(args):
    if min(args.members, args.epochs, args.patience, args.batch_size, args.threads) <= 0:
        raise ValueError("Positive training settings required")
    set_deterministic_execution(args.seed, args.threads)
    device = choose_device(args.device)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    protocol, _ = load_prepared(args.prepared)
    cache, frame, arrays = load_cache(args.cache)
    if cache["protocol_sha256"] != sha(args.prepared/"protocol.json"):
        raise ValueError("Feature cache/protocol mismatch")
    allowed = (frame.split == "train") | ((frame.split == "validation") & (frame.validation_role == "inverse"))
    if not allowed.all():
        raise ValueError("Training must not consume reliability-validation, calibration or test")
    train_indexes = np.flatnonzero(frame.split.to_numpy() == "train")
    val_indexes = np.flatnonzero(frame.split.to_numpy() == "validation")
    mean, std = training_statistics(arrays, train_indexes)
    targets = frame[[n+"_z" for n in NAMES]].to_numpy(dtype=np.float32)
    config = {"cache_signature": cache["signature"], "protocol_sha256": cache["protocol_sha256"],
              "scope": cache["scope"], "members": args.members, "seed": args.seed,
              "member_seeds": [args.seed+1009*m for m in range(args.members)],
              "epochs": args.epochs, "patience": args.patience, "batch_size": args.batch_size,
              "threads": args.threads, "learning_rate": args.learning_rate, "weight_decay": args.weight_decay,
              "variance_floor_z_squared": args.variance_floor, "variance_head": "softplus+floor",
              "loss": "mean Gaussian NLL without additive 0.5*log(2*pi)",
              "model_selection": "lowest inverse-validation Gaussian NLL per independent member",
              "mixture": "equal weights; within=mean(v); between=mean((mu-mean(mu))^2)",
              "feature_mean_train_only": mean, "feature_std_train_only": std,
              "train_count": len(train_indexes), "validation_count": len(val_indexes),
              "lower": protocol["lower"], "upper": protocol["upper"], "parameter_names": list(NAMES),
              "device": str(device), "python": platform.python_version(), "torch": str(torch.__version__),
              "numpy": np.__version__, "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
              "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
              "strict_determinism": True, "tf32": False, "test_evaluated": False,
              "calibrated": False, "sources": {name: sha(ROOT/name) for name in (
                  "c2_estimation/v4/ensemble.py", "c2_estimation/v4/baseline.py",
                  "c2_estimation/v4/features.py", "c2_estimation/v4/data.py", "c2_estimation/pipeline.py")}}
    signature = digest_json(config)
    if args.output.exists() and any(args.output.iterdir()):
        saved = json.loads((args.output/"run_config.json").read_text(encoding="utf-8"))
        if not args.resume or saved["signature"] != signature:
            raise ValueError("Existing run requires --resume with identical config and sources")
    else:
        if args.resume:
            raise ValueError("Cannot resume a missing run")
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output/"run_config.json", {"signature": signature, **config})
    train_data = CachedDataset(arrays, targets, train_indexes, mean, std)
    val_loader = DataLoader(CachedDataset(arrays, targets, val_indexes, mean, std),
                            batch_size=args.batch_size, shuffle=False, num_workers=0)
    val_frame = frame.iloc[val_indexes]
    true_z = val_frame[[n+"_z" for n in NAMES]].to_numpy(dtype=np.float64)
    predictions, variances, members = [], [], []
    start = time.perf_counter()
    for m, member_seed in enumerate(config["member_seeds"]):
        set_deterministic_execution(member_seed, args.threads)
        folder = args.output/f"member_{m:02d}"
        folder.mkdir(exist_ok=True)
        model = GaussianCNN(device, args.variance_floor).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
        history, best, stale, first = [], float("inf"), 0, 1
        if (folder/"last_model.pt").exists():
            last = torch.load(folder/"last_model.pt", map_location=device, weights_only=True)
            if last["signature"] != signature:
                raise ValueError("Member checkpoint/config mismatch")
            model.load_state_dict(last["model"])
            optimizer.load_state_dict(last["optimizer"])
            history, best, stale, first = last["history"], last["best"], last["stale"], last["epoch"]+1
        for epoch in range(first, args.epochs+1):
            if stale >= args.patience:
                break
            loader = DataLoader(train_data, batch_size=args.batch_size, shuffle=True, num_workers=0,
                                generator=torch.Generator().manual_seed(member_seed+epoch))
            model.train()
            train_loss = 0.
            for x, y in loader:
                optimizer.zero_grad(set_to_none=True)
                mu, var = model(x.to(device))
                loss = gaussian_nll(mu, var, y.to(device))
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite ensemble loss")
                loss.backward()
                optimizer.step()
                train_loss += float(loss.detach().cpu())*len(x)
            mu, var = evaluate(model, val_loader, device)
            nll = float(.5*np.mean(np.log(var.astype(np.float64))+np.square(mu-true_z)/var))
            row = {"epoch": epoch, "train_nll": train_loss/len(train_data), "validation_nll": nll,
                   "validation_z_mse": float(np.square(mu-true_z).mean()),
                   "validation_z_mae": float(np.abs(mu-true_z).mean())}
            history.append(row)
            if nll < best:
                best, stale = nll, 0
                atomic_checkpoint(folder/"best_model.pt", {"model": model.state_dict(), "epoch": epoch,
                                  "signature": signature, "member_seed": member_seed})
            else:
                stale += 1
            atomic_checkpoint(folder/"last_model.pt", {"model": model.state_dict(),
                              "optimizer": optimizer.state_dict(), "history": history,
                              "best": best, "stale": stale, "epoch": epoch, "signature": signature})
            pd.DataFrame(history).to_csv(folder/"training_history.csv", index=False)
            print(f"Member {m+1}/{args.members} epoch {epoch}/{args.epochs}: NLL={nll:.6f} MAE={row['validation_z_mae']:.6f}; elapsed={time.perf_counter()-start:.1f}s", flush=True)
        saved = torch.load(folder/"best_model.pt", map_location=device, weights_only=True)
        model.load_state_dict(saved["model"])
        mu, var = evaluate(model, val_loader, device)
        reloaded = GaussianCNN(device, args.variance_floor).to(device)
        reloaded.load_state_dict(saved["model"])
        check_mu, check_var = evaluate(reloaded, val_loader, device)
        if not np.array_equal(mu, check_mu) or not np.array_equal(var, check_var):
            raise ValueError("Reloaded member does not reproduce predictions exactly")
        predictions.append(mu)
        variances.append(var)
        members.append({"member": m, "seed": member_seed, "best_epoch": saved["epoch"],
                        "best_validation_nll": best, "checkpoint_sha256": sha(folder/"best_model.pt"),
                        "checkpoint_reload_exact": True})
        write_json(folder/"summary.json", members[-1])
        del model, optimizer, reloaded
    predictions, variances = np.stack(predictions), np.stack(variances)
    predicted, within, between, total = combine(predictions, variances)
    result = prediction_frame(val_frame, predictions, variances, np.array(config["lower"]), np.array(config["upper"]))
    result.to_csv(args.output/"validation_predictions.csv", index=False)
    np.savez_compressed(args.output/"validation_member_moments.npz", means=predictions, variances=variances)
    pd.DataFrame(regression_metrics(predicted, true_z, np.array(config["lower"]), np.array(config["upper"]))).to_csv(args.output/"parameter_metrics.csv", index=False)
    summary = {"status": "completed_probabilistic_ensemble", "members": members,
               "macro_validation_z_mae": float(np.abs(predicted-true_z).mean()),
               "validation_z_mse": float(np.square(predicted-true_z).mean()),
               "mean_within_variance_z": within.mean(axis=0).tolist(),
               "mean_between_variance_z": between.mean(axis=0).tolist(),
               "predictions_sha256": sha(args.output/"validation_predictions.csv"),
               "member_moments_sha256": sha(args.output/"validation_member_moments.npz"),
               "test_evaluated": False, "calibrated": False,
               "elapsed_this_invocation_seconds": time.perf_counter()-start}
    write_json(args.output/"summary.json", summary)
    print(json.dumps(summary), flush=True)
    return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--members", type=int, default=3)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--patience", type=int, default=12)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--learning-rate", type=float, default=.001)
    p.add_argument("--weight-decay", type=float, default=.0001)
    p.add_argument("--variance-floor", type=float, default=1e-4)
    p.add_argument("--device", choices=("cpu", "cuda", "auto"), default="auto")
    p.add_argument("--resume", action="store_true")
    return p


if __name__ == "__main__":
    train(parser().parse_args())
