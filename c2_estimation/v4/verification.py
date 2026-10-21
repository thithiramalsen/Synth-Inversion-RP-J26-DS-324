"""Save implementation-test logs/counts and source fingerprints as research evidence."""
import argparse
from pathlib import Path
import platform
import time
import unittest

import torch

from c2_estimation.v4.data import ROOT, sha, write_json


def verify(args):
    if args.output.exists():
        raise ValueError("Verification output must be new")
    if args.gpu_only:
        if not torch.cuda.is_available():
            raise ValueError("GPU verification requires the CUDA overlay")
        names = ["c2_estimation.tests.test_v4.FeatureAndModelTests.test_cuda_training_step_is_strictly_reproducible",
                 "c2_estimation.tests.test_ensemble.EnsembleTests.test_cuda_gaussian_step_reproduces_exactly"]
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    else:
        suite = unittest.defaultTestLoader.discover(str(ROOT/"c2_estimation/tests"),pattern="test*.py")
    args.output.mkdir(parents=True)
    started = time.perf_counter()
    with (args.output/"tests.log").open("w",encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    summary = {"status":"passed" if result.wasSuccessful() else "failed", "synthetic_only":True,
        "test_set_evaluated":False,"tests_run":result.testsRun,"skipped":len(result.skipped),
        "skip_reasons":[{"test":str(test),"reason":reason} for test,reason in result.skipped],
        "failures":[str(test) for test,_ in result.failures],"errors":[str(test) for test,_ in result.errors],
        "gpu_only":args.gpu_only,"torch":str(torch.__version__),"python":platform.python_version(),
        "elapsed_seconds":time.perf_counter()-started,"log_sha256":sha(args.output/"tests.log"),
        "sources":{str(p.relative_to(ROOT)).replace("\\","/"):sha(p) for p in sorted((ROOT/"c2_estimation/v4").glob("*.py"))},
        "test_sources":{p.name:sha(p) for p in sorted((ROOT/"c2_estimation/tests").glob("test*.py"))}}
    write_json(args.output/"verification.json",summary)
    print(f"{summary['status']}: {result.testsRun} tests; {len(result.skipped)} skipped; saved {args.output}",flush=True)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--gpu-only",action="store_true")
    verify(parser.parse_args())
