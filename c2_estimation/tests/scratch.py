"""One disposable C2-only location; no scattered folders or shared study data."""
from pathlib import Path
import tempfile


def temporary_directory(*, prefix="c2-test-"):
    if not prefix or any(not (character.isalnum() or character in "-_") for character in prefix):
        raise ValueError("Use a simple C2 fixture prefix without path separators")
    root = Path(__file__).resolve().parents[2] / "data/processed/c2_v4/_scratch/tests"
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=root)
