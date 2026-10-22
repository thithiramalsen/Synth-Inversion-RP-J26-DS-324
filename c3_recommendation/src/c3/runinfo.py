"""Provenance helpers recorded in every run_config.json."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .config import REPO_ROOT

PACKAGES = ("numpy", "pandas", "pyarrow", "scipy", "pyyaml", "soundfile", "matplotlib", "torch", "transformers")


def git_state() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    try:
        return {"commit": run("rev-parse", "HEAD"),
                "c3_uncommitted_changes": bool(run("status", "--porcelain", "--", "c3_recommendation"))}
    except OSError:
        return {"commit": None, "c3_uncommitted_changes": None}


def package_versions() -> dict:
    out = {"python": platform.python_version()}
    for name in PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
