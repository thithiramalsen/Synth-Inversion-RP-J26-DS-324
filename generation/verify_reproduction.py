"""Check regenerated artifacts against a shared reference without changing files."""
import argparse
import hashlib
import json
import struct
from pathlib import Path


def waveform_digest(path):
    """Hash WAV format and exact sample bytes; ignore PEAK creation timestamps."""
    raw = path.read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"Expected RIFF WAV: {path}")
    chunks = {}
    offset = 12
    while offset + 8 <= len(raw):
        tag = raw[offset:offset+4]
        size = struct.unpack("<I", raw[offset+4:offset+8])[0]
        end = offset + 8 + size
        if end > len(raw):
            raise ValueError(f"Truncated WAV: {path}")
        if tag in (b"fmt ", b"data"):
            if tag in chunks:
                raise ValueError(f"Repeated WAV chunk: {path}")
            chunks[tag] = raw[offset+8:end]
        offset = end + size % 2
    if set(chunks) != {b"fmt ", b"data"}:
        raise ValueError(f"Missing WAV format/audio chunk: {path}")
    digest = hashlib.sha256()
    for tag in (b"fmt ", b"data"):
        digest.update(tag)
        digest.update(struct.pack("<Q", len(chunks[tag])))
        digest.update(chunks[tag])
    return digest.hexdigest()


def verify(reference, root, stage):
    root = root.resolve()
    expected = json.loads(reference.read_text(encoding="utf-8"))
    groups = ["recipe", "candidates"] + (["pilot"] if stage == "all" else [])
    failures = []
    checked = 0
    for group in groups:
        for relative, checksum in expected["files"][group].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Reference contains a path outside the dataset root")
            checked += 1
            if not path.is_file():
                failures.append((relative, "missing"))
            elif (hashlib.sha256(path.read_bytes()).hexdigest() if group == "recipe"
                  else waveform_digest(path)) != checksum:
                failures.append((relative, "hash mismatch"))
    print(f"Checked {checked} files; {len(failures)} failures.")
    for relative, reason in failures[:20]:
        print(f"{reason}: {relative}")
    if failures:
        print("Do not label this reproduction identical. Check recipe and binary/runtime versions.")
        return 1
    print("Recipe files and exact WAV sample bytes/formats match the reference.")
    print("WAV header timestamps, machine paths and metadata creation dates are not compared.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage", choices=("candidates", "all"), default="all")
    args = parser.parse_args()
    raise SystemExit(verify(args.reference, args.root, args.stage))
