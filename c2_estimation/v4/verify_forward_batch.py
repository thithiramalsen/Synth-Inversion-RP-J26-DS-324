"""Cross-check the batch diagnostic core against the saved full-baseline example."""
import os
# Match the production batch's single-thread BLAS policy BEFORE importing NumPy.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np
import pandas as pd

from c2_estimation.v4.data import DEFAULT_PREPARED, load_prepared, sha, write_json
from c2_estimation.v4.diagnostic_batch import initialize, measure, worker
from c2_estimation.v4.diagnostics import Renderer


def verify(args):
    if args.output.exists():
        raise ValueError("Verification output must be new")
    protocol,frame = load_prepared(args.prepared)
    example = json.loads((args.example/"example.json").read_text(encoding="utf-8"))
    predictions_path = args.run/"validation_predictions.csv"
    if sha(predictions_path) != example["predictions_sha256"]:
        raise ValueError("Worked-example frozen predictions changed")
    predictions = pd.read_csv(predictions_path,float_precision="round_trip")
    prediction = predictions[predictions.sample_id == example["sample_id"]].iloc[0].to_dict()
    source = frame[frame.sample_id == example["sample_id"]].iloc[0].to_dict()
    if source["split"] != "validation" or source["validation_role"] != "inverse":
        raise ValueError("Verification is inverse-validation only")
    result = measure(source,prediction,Renderer(protocol["recipe"]),audit=True)
    if args.workers>1:
        with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(protocol["recipe"],)) as executor:
            records = list(executor.map(worker,[(source,prediction,.02,True)]*args.workers))
        args.output.mkdir(parents=True)
        write_json(args.output/"cross_process_comparison.json",{"serial":result,"workers":records})
        for record in records:
            if record != result:
                raise ValueError("Spawn-worker diagnostic differs from serial measurement")
    previous = pd.read_csv(args.example/"parameter_diagnostics.csv",float_precision="round_trip")
    if abs(result["R"]-example["R"]["distance"])>1e-12:
        raise ValueError("Batch/worked-example reconstruction mismatch")
    np.testing.assert_allclose([s["S"] for s in result["sensitivities"]],previous.sensitivity,rtol=0,atol=1e-10)
    if sha(predictions_path) != example["predictions_sha256"]:
        raise ValueError("Diagnostic changed frozen prediction CSV")
    args.output.mkdir(parents=True,exist_ok=True)
    write_json(args.output/"verification.json",{"status":"passed","batch_matches_worked_example":True,
        "test_evaluated":False,"predictions_unchanged":True,"predictions_sha256":sha(predictions_path),
        "parallel_workers_checked":args.workers if args.workers>1 else 0,
        "blas_threads":1,
        "source_sha256":sha(Path(__file__)),"batch_source_sha256":sha(Path(__file__).with_name("diagnostic_batch.py")),
        "measured":result})
    print("Batch/worked-example reconstruction and all 13 sensitivities match; roundtrip, repeat, inactivity and frozen-prediction checks passed",flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,default=DEFAULT_PREPARED)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--example",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=1)
    verify(parser.parse_args())
