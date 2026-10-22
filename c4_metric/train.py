"""Train only a small projection head from frozen encoder preference triplets."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from c4_metric.model import TripletProjection, cosine_distance, triplet_margin_loss

MARK = "SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"
PILOT_MARK = "REHEARSAL_PILOT_DO_NOT_USE_AS_VALIDATED_HUMAN_STUDY_RESULTS"


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest_split_rows(path: Path, split_name: str) -> str:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        selected = [row for row in csv.DictReader(handle) if row.get("split") == split_name]
    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_arrays(triplet_path: Path, embedding_path: Path, *, allow_synthetic: bool,
                allow_pilot_rehearsal: bool = False):
    with triplet_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    with np.load(embedding_path, allow_pickle=False) as archive:
        sample_ids = archive["sample_ids"].astype(str)
        embeddings = np.asarray(archive["embeddings"], dtype=np.float32)
    if embeddings.ndim != 2 or embeddings.shape[0] != len(sample_ids):
        raise ValueError("Embedding cache must have [sample, dimension] embeddings and sample_ids")
    if len(set(sample_ids)) != len(sample_ids) or not np.isfinite(embeddings).all():
        raise ValueError("Embedding cache has duplicate IDs or non-finite values")
    index = {sample_id: i for i, sample_id in enumerate(sample_ids)}
    required = {"anchor_id", "positive_id", "negative_id", "split"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"Triplets CSV must contain {sorted(required)}; run response processing and splits first")
    synthetic = any("SYNTHETIC" in row.get("data_status", "") for row in rows)
    pilot = any(row.get("data_status", "") == PILOT_MARK for row in rows)
    if pilot and any(row.get("data_status", "") != PILOT_MARK for row in rows):
        raise ValueError("Do not mix rehearsal pilot triplets with other data statuses")
    if pilot and not allow_pilot_rehearsal:
        raise ValueError("Rehearsal pilot preferences require explicit --pilot-rehearsal")
    if allow_pilot_rehearsal and not pilot:
        raise ValueError("--pilot-rehearsal accepts only marked rehearsal pilot triplets")
    if synthetic and any("SYNTHETIC" not in row.get("data_status", "") for row in rows):
        raise ValueError("Do not mix synthetic and human preference triplets")
    if synthetic and not allow_synthetic:
        raise ValueError("Synthetic preferences require explicit --allow-synthetic")
    selected = {name: [] for name in ("train", "validation", "test")}
    missing = set()
    excluded_votes = {"tie": 0, "unresolved": 0}
    for row in rows:
        vote_status = row.get("vote_status", "preference") or "preference"
        if vote_status in excluded_votes:
            excluded_votes[vote_status] += 1
            continue
        if vote_status not in {"preference", "majority", ""}:
            raise ValueError(f"Unknown vote_status {vote_status!r}; refusing ambiguous training data")
        split = row["split"]
        if split not in selected:
            raise ValueError(f"Unknown split label: {split}")
        if split == "test":
            continue
        ids = (row["anchor_id"], row["positive_id"], row["negative_id"])
        missing.update(set(ids) - index.keys())
        if not set(ids).issubset(index):
            continue
        selected[split].append([index[sid] for sid in ids])
    if missing:
        sample = sorted(missing)[:8]
        raise ValueError(f"Embedding cache is missing {len(missing)} audio IDs, e.g. {sample}")
    if not selected["train"] or not selected["validation"]:
        raise ValueError("Training and validation splits must both contain preference triplets")
    if excluded_votes["tie"] or excluded_votes["unresolved"]:
        print(f"Excluded ambiguous comparisons from triplet loss: {excluded_votes}")
    return embeddings, selected, sum(row.get("split") == "test" for row in rows), synthetic


def batch_metrics(model, tensors, margin: float) -> tuple[float, float]:
    model.eval()
    total_loss = 0.0
    total_correct = 0
    count = 0
    loader = DataLoader(tensors, batch_size=256, shuffle=False, num_workers=0)
    with torch.no_grad():
        for a, p, n in loader:
            a, p, n = model(a), model(p), model(n)
            loss = triplet_margin_loss(a, p, n, margin)
            dap, dan = cosine_distance(a, p), cosine_distance(a, n)
            total_loss += float(loss) * len(a)
            total_correct += int((dap < dan).sum())
            count += len(a)
    return total_loss / count, total_correct / count


def smoke_test(triplet_path: Path, embedding_path: Path, *, margin: float = 0.2,
               allow_synthetic: bool = False, allow_pilot_rehearsal: bool = False) -> dict:
    """Verify a real batch, finite gradients and one optimizer update without saving."""
    embeddings, split_indices, _, synthetic = load_arrays(
        triplet_path, embedding_path, allow_synthetic=allow_synthetic,
        allow_pilot_rehearsal=allow_pilot_rehearsal)
    indices = np.asarray(split_indices["train"], dtype=np.int64)
    batch = torch.from_numpy(embeddings[indices[:min(4, len(indices))]])
    if batch.ndim != 3 or batch.shape[1:] != (3, embeddings.shape[1]):
        raise ValueError(f"Smoke-test batch has unexpected shape {tuple(batch.shape)}")
    model = TripletProjection(embeddings.shape[1], min(16, embeddings.shape[1]))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    before = [parameter.detach().clone() for parameter in model.parameters()]
    optimizer.zero_grad(set_to_none=True)
    loss = triplet_margin_loss(*(model(batch[:, slot, :]) for slot in range(3)), margin)
    if not torch.isfinite(loss):
        raise FloatingPointError("Smoke-test loss is non-finite")
    loss.backward()
    gradients_finite = all(parameter.grad is not None and torch.isfinite(parameter.grad).all()
                           for parameter in model.parameters())
    if not gradients_finite:
        raise FloatingPointError("Smoke-test did not produce finite gradients")
    optimizer.step()
    updated = any(not torch.equal(old, new.detach()) for old, new in zip(before, model.parameters()))
    if not updated:
        raise RuntimeError("Smoke-test optimizer did not update model parameters")
    return {"status": "passed", "pilot_rehearsal": allow_pilot_rehearsal,
            "synthetic": synthetic, "batch_triplets": int(batch.shape[0]),
            "embedding_dimension": int(embeddings.shape[1]), "loss": float(loss.detach()),
            "forward_pass": "passed", "gradients_finite": gradients_finite,
            "optimizer_updated_parameters": updated}


def train(triplet_path: Path, embedding_path: Path, output_dir: Path, *,
          output_dim: int = 64, margin: float = 0.2, learning_rate: float = 1e-3,
          batch_size: int = 64, epochs: int = 100, patience: int = 12,
          seed: int = 20261014, allow_synthetic: bool = False,
          allow_pilot_rehearsal: bool = False) -> dict:
    if output_dim < 1 or margin < 0 or learning_rate <= 0 or batch_size < 1 or epochs < 1 or patience < 1:
        raise ValueError("Invalid model/training configuration")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    embeddings, split_indices, test_row_count, synthetic = load_arrays(
        triplet_path, embedding_path, allow_synthetic=allow_synthetic,
        allow_pilot_rehearsal=allow_pilot_rehearsal)
    with triplet_path.open(newline="", encoding="utf-8-sig") as handle:
        pilot_rehearsal = any(row.get("data_status", "") == PILOT_MARK
                              for row in csv.DictReader(handle))
    if pilot_rehearsal and output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing rehearsal pilot outputs: {output_dir}")
    embedding_meta_path = embedding_path.with_suffix(".json")
    embedding_meta = (json.loads(embedding_meta_path.read_text(encoding="utf-8"))
                      if embedding_meta_path.is_file() else {})
    cache_status = embedding_meta.get("data_status")
    allowed_cache_statuses = ({PILOT_MARK} if pilot_rehearsal else
                              {MARK, "frozen_encoder_embeddings"} if synthetic else
                              {"human_response", "frozen_encoder_embeddings"})
    if cache_status and cache_status not in allowed_cache_statuses:
        raise ValueError("Triplet data status does not match the embedding cache metadata")
    encoder_model = embedding_meta.get("model", "synthetic_or_unspecified_encoder")
    encoder_revision = embedding_meta.get("revision")
    metadata_dimension = embedding_meta.get("embedding_dimension")
    if metadata_dimension is not None and int(metadata_dimension) != embeddings.shape[1]:
        raise ValueError("Embedding cache metadata dimension does not match its vectors")
    if encoder_model == "laion/clap-htsat-unfused" and embeddings.shape[1] != 512:
        raise ValueError("Pinned CLAP embeddings must have dimension 512")
    split_manifest_hash = digest_file(triplet_path)
    split_hashes = {name: digest_split_rows(triplet_path, name)
                    for name in ("train", "validation", "test")}
    train_x = np.asarray(split_indices["train"], dtype=np.int64)
    val_x = np.asarray(split_indices["validation"], dtype=np.int64)
    def tensor_set(index_rows):
        values = torch.from_numpy(embeddings[index_rows])
        return TensorDataset(values[:, 0, :], values[:, 1, :], values[:, 2, :])
    train_data, val_data = tensor_set(train_x), tensor_set(val_x)
    loader = DataLoader(train_data, batch_size=batch_size, shuffle=True,
                         generator=torch.Generator().manual_seed(seed), num_workers=0)
    model = TripletProjection(embeddings.shape[1], output_dim)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    output_dir.mkdir(parents=True, exist_ok=True)
    best_loss = float("inf")
    best_epoch = 0
    wait = 0
    history = []
    started = time.time()
    checkpoint_path = output_dir / "best_model.pt"
    for epoch in range(1, epochs + 1):
        model.train()
        running = 0.0
        count = 0
        for a, p, n in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = triplet_margin_loss(model(a), model(p), model(n), margin)
            if not torch.isfinite(loss):
                raise FloatingPointError("Non-finite triplet loss")
            loss.backward()
            if any(parameter.grad is not None and not torch.isfinite(parameter.grad).all()
                   for parameter in model.parameters()):
                raise FloatingPointError("Non-finite gradient in projection head")
            optimizer.step()
            running += float(loss.detach()) * len(a)
            count += len(a)
        train_loss = running / count
        val_loss, val_accuracy = batch_metrics(model, val_data, margin)
        history_row = {"epoch": epoch, "train_loss": train_loss,
                       "validation_loss": val_loss,
                       "validation_preference_accuracy_diagnostic": val_accuracy}
        if pilot_rehearsal:
            history_row.update({"data_status": PILOT_MARK, "pilot_rehearsal": True})
        history.append(history_row)
        if val_loss < best_loss - 1e-8:
            best_loss, best_epoch, wait = val_loss, epoch, 0
            torch.save({"model_state_dict": model.state_dict(),
                        "input_dim": embeddings.shape[1], "output_dim": output_dim,
                        "normalize": True, "margin": margin,
                        "distance": "cosine distance = 1 - cosine similarity",
                        "encoder_model": encoder_model,
                        "encoder_revision": encoder_revision,
                        "data_status": MARK if synthetic else PILOT_MARK if pilot_rehearsal else "human_response",
                        "pilot_rehearsal": pilot_rehearsal,
                        "best_epoch": epoch, "seed": seed,
                        "split_manifest_sha256": split_manifest_hash,
                        "train_triplets_sha256": split_hashes["train"],
                        "validation_triplets_sha256": split_hashes["validation"],
                        "test_triplets_sha256": split_hashes["test"],
                        "training_split_name": "train",
                        "checkpoint_selection_split": "validation",
                        "test_labels_used_for_training_or_selection": False}, checkpoint_path)
        else:
            wait += 1
        if wait >= patience:
            break
    with (output_dir / "training_history.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)
    run = {
        "data_status": MARK if synthetic else PILOT_MARK if pilot_rehearsal else "human_response",
        "synthetic_evidence": synthetic,
        "pilot_rehearsal": pilot_rehearsal,
        "train_triplets": len(train_data), "validation_triplets": len(val_data),
        "test_rows_present_but_not_used": test_row_count,
        "embedding_dimension": int(embeddings.shape[1]), "projection_dimension": output_dim,
        "encoder": "frozen precomputed embeddings; encoder not fine-tuned",
        "encoder_model": encoder_model, "encoder_revision": encoder_revision,
        "loss": "mean(max(0, cosine_distance(A,P) - cosine_distance(A,N) + margin))",
        "margin": margin, "optimizer": "AdamW", "learning_rate": learning_rate,
        "batch_size": batch_size, "epochs_completed": len(history), "best_epoch": best_epoch,
        "best_validation_loss": best_loss, "seed": seed,
        "triplets_sha256": split_manifest_hash,
        "train_triplets_sha256": split_hashes["train"],
        "validation_triplets_sha256": split_hashes["validation"],
        "test_triplets_sha256": split_hashes["test"],
        "training_split_name": "train",
        "checkpoint_selection_split": "validation",
        "test_labels_used_for_training_or_selection": False,
        "embedding_cache_sha256": digest_file(embedding_path),
        "checkpoint": str(checkpoint_path), "elapsed_seconds": round(time.time() - started, 3),
        "checkpoint_sha256": digest_file(checkpoint_path),
        "note": "Only train triplets contribute to loss and gradients; validation selects the checkpoint; test labels are not used for training or model selection.",
    }
    (output_dir / "run_config.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triplets", type=Path, required=True, help="Preference triplets with train/validation/test split")
    parser.add_argument("--embeddings", type=Path, required=True, help="NPZ containing sample_ids and embeddings")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "c4_metric/outputs/training")
    parser.add_argument("--output-dim", type=int, default=64)
    parser.add_argument("--margin", type=float, default=0.2)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--patience", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--pilot-rehearsal", action="store_true",
                        help="Explicitly train on marked rehearsal pilot data")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run one batch and verify loss, gradients and an optimizer update without saving")
    args = parser.parse_args()
    if args.smoke_test:
        print(json.dumps(smoke_test(args.triplets, args.embeddings, margin=args.margin,
                                    allow_synthetic=args.allow_synthetic,
                                    allow_pilot_rehearsal=args.pilot_rehearsal), indent=2))
        return
    print(json.dumps(train(args.triplets, args.embeddings, args.output_dir,
                           output_dim=args.output_dim, margin=args.margin,
                           learning_rate=args.learning_rate, batch_size=args.batch_size,
                           epochs=args.epochs, patience=args.patience, seed=args.seed,
                           allow_synthetic=args.allow_synthetic,
                           allow_pilot_rehearsal=args.pilot_rehearsal), indent=2))


if __name__ == "__main__":
    main()
