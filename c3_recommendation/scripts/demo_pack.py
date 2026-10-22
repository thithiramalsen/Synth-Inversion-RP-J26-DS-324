"""Package the built demo viewer into one shareable folder + zip (no Python needed to view it).

Copies demo_<rep>.html and ONLY the audio clips that page uses, adds a short README, and zips it.
Audio is never committed to git (rule R4); share the zip on Teams / Google Drive instead.

Usage (repo root, after scripts/demo_build_viewer.py):
    python c3_recommendation/scripts/demo_pack.py [--rep mfcc26]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.config import load_config  # noqa: E402

README = """C3 recommendation demo ({label})
==================================

How to open
-----------
1. Unzip this folder (do not open the page from inside the zip).
2. Double-click  {page}  - it opens in Edge or Chrome. No internet or installation needed.
3. Keep the "clips" folder next to the page; it holds the {n_clips} sounds the page plays.

What it shows
-------------
For 8 validation target sounds: the plain top 5 closest-sounding patches and the C3 (MMR)
picks from the same 100-sound shortlist, with playable audio, the 13 knob settings as bars,
and set metrics. The dial changes lambda (1.0 = plain top 5). It starts at the Phase 7 value.
Illustration only - validation sounds, not the final test result.

Rebuild from the repository (needs the corpus_v4 audio and the feature cache)
----------------------------------------------------------------------------
    .\\venv\\Scripts\\Activate.ps1
    python c3_recommendation/scripts/06_extract_features.py      # once, about 15 minutes
    python c3_recommendation/scripts/demo_build_viewer.py
    python c3_recommendation/scripts/demo_pack.py

Built {built} by D.A.V.P. Waidyarathne, component C3.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--rep", default="mfcc26", choices=("mfcc26", "logmel_stats"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    demo_dir = cfg.path("outputs_dir") / "demo"
    page = demo_dir / f"demo_{args.rep}.html"
    data_file = demo_dir / f"demo_data_{args.rep}.json"
    if not page.exists() or not data_file.exists():
        raise SystemExit(f"{page.name} not built yet: run scripts/demo_build_viewer.py first")
    clips = json.loads(data_file.read_text(encoding="utf-8"))["clips"]
    missing = [c for c in clips if not (demo_dir / "clips" / f"{c}.wav").exists()]
    if missing:
        raise SystemExit(f"{len(missing)} clips missing (e.g. {missing[0]}); rebuild the demo first")

    name = f"c3_demo_{args.rep}"
    pack_root = cfg.path("outputs_dir") / "demo_pack"
    target = pack_root / name
    if target.exists():
        shutil.rmtree(target)  # generated folder only; rebuilt from the demo outputs each time
    (target / "clips").mkdir(parents=True)
    shutil.copyfile(page, target / page.name)
    for clip in clips:
        shutil.copyfile(demo_dir / "clips" / f"{clip}.wav", target / "clips" / f"{clip}.wav")
    label = {"mfcc26": "MFCC-26", "logmel_stats": "Log-mel"}[args.rep]
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (target / "README.txt").write_text(README.format(label=label, page=page.name, n_clips=len(clips), built=built),
                                       encoding="utf-8")
    archive = shutil.make_archive(str(pack_root / name), "zip", root_dir=pack_root, base_dir=name)
    size_mb = Path(archive).stat().st_size / 1e6
    print(f"Pack folder: {target}")
    print(f"Zip to share: {archive}  ({size_mb:.1f} MB, {len(clips)} clips)")


if __name__ == "__main__":
    main()
