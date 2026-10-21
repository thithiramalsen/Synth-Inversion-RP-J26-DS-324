"""Resumable forward diagnostics around frozen predictions, not patch refinement."""
from __future__ import annotations

import os
# Each spawn worker has one BLAS thread; do not oversubscribe FFT/norm operations.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from c2_estimation.v4.data import DEFAULT_PREPARED, NAMES, ROOT, digest_json, load_prepared, sha, write_json
from c2_estimation.v4.diagnostics import DISTANCE_CONFIG, Renderer, distance, feature_distance, perturbation_pair, representation
from generation.corpus_audio import load_audio, sample_digest

_renderer = None


def initialize(recipe):
    global _renderer
    _renderer = Renderer(recipe)


def measure(source, prediction, renderer, delta=.02, audit=False):
    z = np.array([prediction[n+"_predicted_z"] for n in NAMES],dtype=np.float64)
    frozen = z.copy()
    target,rate = load_audio(source,ROOT,verify=True)
    if rate != 44100:
        raise ValueError("Unexpected diagnostic sample rate")
    base,actual_base = renderer.render(z)
    target_features,base_features = representation(target),representation(base)
    residual = feature_distance(target_features,base_features)
    result = {"sample_id":source["sample_id"],"R":residual["distance"],
              "R_resolutions":residual["resolutions"],"target_sha256":sample_digest(target),
              "rendered_sha256":sample_digest(base),"sensitivities":[],"audit":None}
    for j,name in enumerate(NAMES):
        minus,plus,mode = perturbation_pair(z,j,delta)
        if np.array_equal(minus,z):
            a,actual_a,a_features = base,actual_base,base_features
        else:
            a,actual_a = renderer.render(minus)
            a_features = representation(a)
        if np.array_equal(plus,z):
            b,actual_b,b_features = base,actual_base,base_features
        else:
            b,actual_b = renderer.render(plus)
            b_features = representation(b)
        other = np.arange(13) != j
        if not np.array_equal(actual_a[other],actual_base[other]) or not np.array_equal(actual_b[other],actual_base[other]):
            raise ValueError("Another control changed during perturbation")
        step = float(actual_b[j]-actual_a[j])
        if step <= 0:
            raise ValueError("Engine readback erased the perturbation")
        change = feature_distance(a_features,b_features)["distance"]
        result["sensitivities"].append({"parameter":name,"S":change/step,"actual_step_z":step,
            "mode":mode,"minus_plus_distance":change,"minus_actual_z":float(actual_a[j]),
            "plus_actual_z":float(actual_b[j])})
    if audit:
        repeat,_ = renderer.render(z)
        true_z = np.array([source[n+"_z"] for n in NAMES],dtype=np.float64)
        true_audio,_ = renderer.render(true_z)
        inactive = np.full(13,.5)
        inactive[9] = 0.
        a,b,_ = perturbation_pair(inactive,10,delta)
        inactive_a,_ = renderer.render(a)
        inactive_b,_ = renderer.render(b)
        check = {"repeat_exact":bool(np.array_equal(base,repeat)),
                 "true_roundtrip_exact":bool(np.array_equal(target,true_audio)),
                 "true_roundtrip_distance":distance(target,true_audio),
                 "inactive_env_attack_distance":distance(inactive_a,inactive_b)}
        if not check["repeat_exact"] or not check["true_roundtrip_exact"] or check["inactive_env_attack_distance"] > 1e-8:
            raise ValueError("Renderer positive-control audit failed")
        result["audit"] = check
    if not np.array_equal(z,frozen):
        raise ValueError("Diagnostics changed delivered parameters")
    result["prediction_unchanged"] = True
    return result


def worker(task):
    source,prediction,delta,audit = task
    return measure(source,prediction,_renderer,delta,audit)


def validate_input(prepared,folder):
    protocol,frame = load_prepared(prepared)
    metadata = json.loads((folder/"predictions.json").read_text(encoding="utf-8"))
    if metadata["protocol_sha256"] != sha(prepared/"protocol.json") or metadata["test_evaluated"]:
        raise ValueError("Prediction/protocol mismatch or unexpected test predictions")
    for file,checksum in metadata["files"].items():
        if sha(folder/file) != checksum:
            raise ValueError("Frozen predictions changed: "+file)
    prediction = pd.read_parquet(folder/"predictions.parquet")
    if prediction.sample_id.duplicated().any() or prediction.sample_id.tolist() != metadata["sample_ids"]:
        raise ValueError("Prediction identity mismatch")
    source = frame.set_index("sample_id",drop=False).loc[prediction.sample_id].reset_index(drop=True)
    from c2_estimation.v4.predict_subsets import select
    expected = select(frame,metadata["partition"])
    if source.sample_id.tolist() != expected.sample_id.tolist():
        raise ValueError("Diagnostic IDs differ from frozen preassigned subset")
    actual = source[[n+"_z" for n in NAMES]].to_numpy(dtype=np.float64)
    exported = prediction[[n+"_actual_z" for n in NAMES]].to_numpy(dtype=np.float64)
    if not np.array_equal(actual,exported):
        raise ValueError("Prediction labels differ from actual readbacks")
    return protocol,metadata,source,prediction


def run(args):
    if args.workers < 1 or not 0 < args.delta <= .5:
        raise ValueError("Invalid workers/delta")
    protocol,metadata,source,prediction = validate_input(args.prepared,args.predictions)
    signature_data = {"protocol_sha256":metadata["protocol_sha256"],
        "ensemble_config_sha256":metadata["ensemble_config_sha256"],
        "member_checkpoints":metadata["member_checkpoints"],
        "prediction_metadata_sha256":sha(args.predictions/"predictions.json"),
        "predictions_sha256":metadata["files"]["predictions.parquet"],
        "partition":metadata["partition"],"delta_z":args.delta,"distance_config":DISTANCE_CONFIG,
        "sources":{name:sha(ROOT/name) for name in ("c2_estimation/v4/diagnostic_batch.py",
            "c2_estimation/v4/diagnostics.py","generation/corpus_audio.py","generation/audio_processing.py")},
        "audit_selection":"first four diagnostic ranks, selected without errors",
        "test_evaluated":False,"predictions_refined":False}
    signature = digest_json(signature_data)
    config_path = args.output/"run_config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config["signature"] != signature:
            raise ValueError("Existing diagnostic configuration differs")
    else:
        if args.output.exists() and any(args.output.iterdir()):
            raise ValueError("Nonempty diagnostic output without matching config")
        (args.output/"cases").mkdir(parents=True,exist_ok=True)
        write_json(config_path,{"signature":signature,**signature_data})
    tasks,complete = [],[]
    for i,(s,p) in enumerate(zip(source.to_dict("records"),prediction.to_dict("records"),strict=True)):
        path = args.output/"cases"/(s["sample_id"]+".json")
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["signature"] != signature or record["sample_id"] != s["sample_id"]:
                raise ValueError("Resumed diagnostic case mismatch")
            checksum = record.pop("content_sha256")
            if digest_json(record) != checksum:
                raise ValueError("Resumed diagnostic case content changed")
            record["content_sha256"] = checksum
            complete.append(record)
        else:
            tasks.append((s,p,args.delta,i < 4))
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(protocol["recipe"],)) as executor:
        for record in executor.map(worker,tasks,chunksize=1):
            record["signature"] = signature
            record["content_sha256"] = digest_json(record)
            write_json(args.output/"cases"/(record["sample_id"]+".json"),record)
            complete.append(record)
            print(f"{metadata['partition']} diagnostics {len(complete)}/{len(source)}; elapsed={time.perf_counter()-started:.1f}s",flush=True)
    mapping = {r["sample_id"]:r for r in complete}
    wide,long = prediction.copy(),[]
    wide["R"] = [mapping[s]["R"] for s in wide.sample_id]
    for j,name in enumerate(NAMES):
        wide[name+"_S"] = [mapping[s]["sensitivities"][j]["S"] for s in wide.sample_id]
    for s in source.sample_id:
        long.extend({"sample_id":s,"R":mapping[s]["R"],**row} for row in mapping[s]["sensitivities"])
    wide.to_parquet(args.output/"diagnostics.parquet",index=False)
    wide.to_csv(args.output/"diagnostics.csv",index=False)
    pd.DataFrame(long).to_csv(args.output/"perturbation_readbacks.csv",index=False)
    # Revalidate the source files after all renderings, not just before.
    for file,checksum in metadata["files"].items():
        if sha(args.predictions/file) != checksum:
            raise ValueError("Diagnostics modified frozen prediction inputs")
    values = wide[["R",*[n+"_S" for n in NAMES]]].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or (values<0).any():
        raise ValueError("Invalid completed diagnostic values")
    result = {"status":"complete", "signature":signature, "partition":metadata["partition"],
        "count":len(wide),"parameter_diagnostic_count":len(long),"delta_z":args.delta,
        "test_evaluated":False,"predictions_unchanged":True,"calibrated":False,
        "audit_count":sum(r["audit"] is not None for r in complete),
        "case_checksums":{p.name:sha(p) for p in sorted((args.output/"cases").glob("*.json"))},
        "files":{file:sha(args.output/file) for file in ("diagnostics.parquet","diagnostics.csv","perturbation_readbacks.csv")},
        "elapsed_this_invocation_seconds":time.perf_counter()-started}
    write_json(args.output/"summary.json",result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,default=DEFAULT_PREPARED)
    parser.add_argument("--predictions",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--delta",type=float,default=.02)
    run(parser.parse_args())
