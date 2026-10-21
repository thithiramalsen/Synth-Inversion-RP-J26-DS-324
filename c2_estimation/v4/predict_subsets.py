"""Freeze ensemble predictions for preassigned NON-TEST diagnostic subsets.

Extracts inputs without fitting any preprocessing statistics. Does not store another
large feature cache and never accesses the held-out test audio.
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from c2_estimation.pipeline import choose_device, create_mel_filterbank, extract_log_mel, preprocessing_settings, set_deterministic_execution
from c2_estimation.v4.data import DEFAULT_PREPARED, NAMES, ROOT, digest_json, load_prepared, sha, write_json
from c2_estimation.v4.ensemble import GaussianCNN, prediction_frame
from generation.corpus_audio import load_audio


def select(frame, partition):
    eligible = frame[frame.diagnostic_rank >= 0]
    if partition == "smoke":
        selected = eligible[eligible.split == "train"]
    elif partition == "calibration":
        selected = eligible[eligible.split == "calibration"]
    elif partition == "reliability-validation":
        selected = eligible[(eligible.split == "validation") & (eligible.validation_role == "reliability")]
    else:
        raise ValueError("Only smoke, calibration and reliability-validation are permitted; test stays locked")
    if selected.empty or (selected.split == "test").any():
        raise ValueError("Invalid diagnostic selection")
    return selected.sort_values("diagnostic_rank").reset_index(drop=True)


def predict(args):
    if min(args.batch_size,args.workers,args.threads) < 1:
        raise ValueError("Positive execution settings required")
    protocol, frame = load_prepared(args.prepared)
    config = json.loads((args.ensemble/"run_config.json").read_text(encoding="utf-8"))
    summary = json.loads((args.ensemble/"summary.json").read_text(encoding="utf-8"))
    if summary["status"] != "completed_probabilistic_ensemble":
        raise ValueError("All ensemble members must be complete before freezing predictions")
    if config["protocol_sha256"] != sha(args.prepared/"protocol.json"):
        raise ValueError("Ensemble/protocol mismatch")
    for path, checksum in config["sources"].items():
        if sha(ROOT/path) != checksum:
            raise ValueError("Training source differs from frozen ensemble: "+path)
    selected = select(frame,args.partition)
    if len(selected) != protocol["diagnostic_counts"]["validation" if args.partition == "reliability-validation" else "train" if args.partition == "smoke" else "calibration"]:
        raise ValueError("Frozen subset count mismatch")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Frozen prediction output must be new")
    settings = preprocessing_settings(protocol["recipe"]["synthesis"])
    window = np.hanning(settings["n_fft"]).astype(np.float32)
    bank = create_mel_filterbank(44100,settings["n_fft"],settings["n_mels"],20.,20000.)
    set_deterministic_execution(config["seed"],args.threads)
    device = choose_device(args.device)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    models = []
    for member in summary["members"]:
        path = args.ensemble/f"member_{member['member']:02d}/best_model.pt"
        if sha(path) != member["checkpoint_sha256"]:
            raise ValueError("Frozen member changed")
        state = torch.load(path,map_location=device,weights_only=True)
        if state["signature"] != config["signature"]:
            raise ValueError("Member/config signature mismatch")
        model = GaussianCNN(device,config["variance_floor_z_squared"]).to(device)
        model.load_state_dict(state["model"])
        model.eval()
        models.append(model)

    def extract(row):
        audio, rate = load_audio(row,ROOT,verify=True)
        if rate != 44100:
            raise ValueError("Unexpected rate")
        mel = extract_log_mel(audio,window,bank,settings["n_fft"],settings["hop_length"],settings["top_db"])
        if mel.shape != (64,259) or not np.isfinite(mel).all():
            raise ValueError("Invalid input feature")
        return (mel-config["feature_mean_train_only"])/config["feature_std_train_only"]

    mean_blocks, variance_blocks = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as executor, torch.no_grad():
        for offset in range(0,len(selected),args.batch_size):
            rows = selected.iloc[offset:offset+args.batch_size].to_dict("records")
            features = np.stack(list(executor.map(extract,rows)))
            x = torch.from_numpy(features[:,None]).to(device)
            means, variances = [], []
            for model in models:
                mu,var = model(x)
                repeat_mu,repeat_var = model(x)
                if not torch.equal(mu,repeat_mu) or not torch.equal(var,repeat_var):
                    raise ValueError("Repeated inference differs")
                means.append(mu.cpu().numpy())
                variances.append(var.cpu().numpy())
            mean_blocks.append(np.stack(means))
            variance_blocks.append(np.stack(variances))
            print(f"Frozen {args.partition} predictions {offset+len(rows)}/{len(selected)}",flush=True)
    means,variances = np.concatenate(mean_blocks,axis=1),np.concatenate(variance_blocks,axis=1)
    predictions = prediction_frame(selected,means,variances,np.array(config["lower"]),np.array(config["upper"]))
    args.output.mkdir(parents=True,exist_ok=True)
    predictions.to_parquet(args.output/"predictions.parquet",index=False)
    predictions.to_csv(args.output/"predictions.csv",index=False)
    np.savez_compressed(args.output/"member_moments.npz",means=means,variances=variances)
    metadata = {"status":"frozen_predictions", "partition":args.partition,"count":len(selected),
        "sample_ids":selected.sample_id.tolist(),"protocol_sha256":config["protocol_sha256"],
        "ensemble_config_sha256":sha(args.ensemble/"run_config.json"),
        "member_checkpoints":[m["checkpoint_sha256"] for m in summary["members"]],
        "device":str(device),"batch_size":args.batch_size,"settings":settings,
        "repeat_inference_exact":True,"raw_and_processed_audio_hashes_verified":True,
        "normalization_fitted_on":"train only, frozen ensemble run statistics",
        "source_sha256":sha(Path(__file__)),"calibrated":False,"test_evaluated":False,
        "files":{p.name:sha(p) for p in args.output.iterdir() if p.is_file()}}
    metadata["signature"] = digest_json(metadata)
    write_json(args.output/"predictions.json",metadata)
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,default=DEFAULT_PREPARED)
    parser.add_argument("--ensemble",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--partition",choices=("smoke","calibration","reliability-validation"),required=True)
    parser.add_argument("--batch-size",type=int,default=128)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--threads",type=int,default=4)
    parser.add_argument("--device",choices=("cpu","cuda","auto"),default="auto")
    predict(parser.parse_args())
