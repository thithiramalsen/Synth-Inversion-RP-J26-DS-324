"""Create a CUDA training overlay while preserving the frozen synthesis venv.

Scientific dependencies are reused read-only from venv; only the CUDA torch wheel
is installed locally in .venv-c2. Run this module with the original venv's Python.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".venv-c2"
CUDA_INDEX = "https://download.pytorch.org/whl/cu130"
TORCH_VERSION = "2.13.0+cu130"


def setup(install: bool):
    source = ROOT / "venv/Lib/site-packages"
    if not source.is_dir():
        raise ValueError("The pinned source venv must exist before creating the training overlay")
    if ENV.is_symlink() or ENV.resolve().parent != ROOT.resolve():
        raise ValueError("Training environment must be the workspace's .venv-c2 directory")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(ENV)], check=True)
    pth = ENV / "Lib/site-packages/c2_frozen_dependencies.pth"
    expected = "../../../venv/Lib/site-packages\n"
    if pth.exists() and pth.read_text(encoding="utf-8").strip() != expected.strip():
        raise ValueError("Existing training dependency overlay differs; inspect it first")
    pth.write_text(expected, encoding="utf-8")
    python = ENV / "Scripts/python.exe"
    if install:
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--no-cache-dir",
                        f"torch=={TORCH_VERSION}", "--index-url", CUDA_INDEX], check=True)
    code = """import importlib.metadata as m, json, sys, torch
names = ['torch','numpy','scipy','pandas','pyarrow','soundfile','matplotlib','vita']
print(json.dumps({'python':sys.version, 'prefix':sys.prefix, 'torch_file':torch.__file__,
 'packages':{n:m.version(n) for n in names}, 'cuda_available':torch.cuda.is_available(),
 'cuda_runtime':torch.version.cuda, 'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
 'cudnn':torch.backends.cudnn.version()}, sort_keys=True))
"""
    result = subprocess.run([str(python), "-B", "-c", code], capture_output=True, text=True, check=True)
    runtime = json.loads(result.stdout)
    runtime.update({"environment_type": "CUDA torch overlay with pinned read-only scientific dependencies",
                    "scientific_dependencies": "venv/Lib/site-packages", "torch_index": CUDA_INDEX})
    if runtime["packages"]["torch"] != TORCH_VERSION or not runtime["cuda_available"]:
        raise RuntimeError("CUDA wheel/GPU unavailable. Rerun with --install before full GPU training.")
    from c2_estimation.v4.data import write_json
    output = ROOT / "data/processed/c2_v4/cuda_environment.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, runtime)
    print(json.dumps(runtime, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Download/install the pinned official CUDA wheel")
    setup(parser.parse_args().install)
