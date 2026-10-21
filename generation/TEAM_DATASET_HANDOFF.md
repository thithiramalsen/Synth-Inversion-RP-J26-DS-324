# Reproduce the completed 131,072-sound research corpus

For the **Git clone + private ZIP + direct full generation** route, use
[TEAM_CLONE_QUICKSTART.md](TEAM_CLONE_QUICKSTART.md). The instructions below
describe the separate extracted-package route with an optional initial
1,024-sound compatibility gate.

Share the completed `team_v4_131072_SHARE.zip` privately with your teammates.
Extract it into a **new folder**, preferably on an SSD with at least **80 GiB
free** for generation. Allow extra space for features, training and backups.
This package includes the exact preset, frozen rendering code, fixed dependency
versions, parameter references and waveform references. Git alone lacks the preset.

## Are the datasets identical?

The same seed (20260803), 13 controls, ranges, parameter order and fixed recipe
produce the same parameter design and stable sample IDs. Actual normalized/native
labels are recorded from the pinned Vita engine, not guessed from UI units.
Compare your local labels with the included Parquet references to establish that
they match exactly. Do not change the sample count, seed, preset, wavetable, bounds,
note, rendering duration, dependencies or processing policy for this reproduction.

Audio is expected to match on compatible builds, but different CPUs, libraries or
operating systems can differ numerically. The full waveform comparison is the
evidence of equality. Matching initial samples or using the same settings alone
does not establish equality of every waveform. WAV creation timestamps and local
paths/file hashes can differ even when raw and processed sample bytes match.

## 1. Verify files and install the fixed runtime

Use **Windows x64, Python 3.13.14** matching the original recorded interpreter.
Check that `python --version` reports that version, then, from the extracted folder:

```powershell
python -B generation/verify_reproduction.py --reference reference/package_integrity.json --stage candidates
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --check --count 131072
```

Resolve any installation/configuration failures before generation. Do not upgrade
Vita or edit code to bypass the checks. CPU/build compatibility must be tested on
each teammate's PC; it is not assumed from this reference-machine audit.

## 2. Optional: first reproduce and verify the original 1,024

```powershell
.\venv\Scripts\python.exe -B -u generation/scripts/05_generate_pilot_dataset.py --profile restricted_bend_sustain_v4 --count 1024
.\venv\Scripts\python.exe -B generation/verify_reproduction.py --reference reference/reference.json --stage candidates
```

This optional compatibility gate uses the historical generator and includes both
raw and processed audio for 1,024 sounds. Do not use that generator for the full
two-copy job. Do not copy reference CSVs, the reference recipe, or another PC's
full manifest into local output/checkpoint directories. Each PC must create its
own file hashes and checkpoints.

## 3. Generate the rest using the single-master parallel runner

```powershell
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --check --count 131072
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --generate --count 131072 --workers 4
```

If step 2 was used, the runner imports that prefix and adds 130,048 sounds.
If it was skipped in a fresh extracted package with no local pilot metadata/audio,
the runner renders all 131,072 directly. Four workers were
a practical choice on the reference machine; use fewer on constrained PCs.
Worker count does not change the recipe. Keep the PC powered and prevent sleep.
The same `--generate` command resumes an interrupted run; there is no overwrite
flag. Complete uncheckpointed WAVs are compared before adoption. Conflicting
files are rejected rather than replaced.

New raw FLOAT masters live under `data/raw/corpus_v4/raw_float/`. The full raw
audio payload is about 64.6 GiB. Imported sounds retain paths to their original
raw folder; keep it. Parameters are checkpointed under `data/raw/corpus_v4/chunks/`
every 128 new rows. CSV/Parquet manifests and summary are consolidated at normal
completion. Do not delete checkpoints when a flat manifest is not yet present.

## 4. Use the shared parameter labels while audio is generating

The references are separate from local generation state:

- `reference/parameters_normalized.parquet`: sample ID/index plus the 13 actual
  normalized Vital control values; a compact target table for most experiments.
- `reference/parameters_full.parquet`: ID/index plus Sobol coordinate, actual
  normalized value, native value and display text for each of the 13 controls.
- `reference/reference_recipe.json`: control order/ranges, seed, fixed settings,
  runtime, preset/code hashes, DC policy and float-underflow policy.
- `generation/PARAMETER_UNITS.md`: unit interpretation, especially cutoff,
  nonlinear envelope times and zero modulation depth.

Example:

```python
import pandas as pd
targets = pd.read_parquet("reference/parameters_normalized.parquet")
print(targets.shape)  # (131072, 15): two identifiers plus 13 controls
```

Match parameters to audio by **sample_id**, not directory listing order.
Only use audio that already exists for experiments requiring waveforms/features;
having all labels available does not mean all local audio has finished rendering.
The full table permits parameter-space experiments immediately. It does not
contain human descriptor/similarity ratings, train/test splits or trained models.

To compare completed local checkpoint labels while rendering continues:

```powershell
.\venv\Scripts\python.exe -B generation/verify_parameter_reference.py --reference reference/parameters_full.parquet --checkpoints data/raw/corpus_v4/chunks
```

A matching prefix verifies only completed rows. It does not certify future audio.
After generation, compare the complete local table:

```powershell
.\venv\Scripts\python.exe -B generation/verify_parameter_reference.py --reference reference/parameters_full.parquet --manifest data/raw/corpus_v4/manifest.parquet
```

## 5. Verify the complete audio dataset

```powershell
.\venv\Scripts\python.exe -B -u -m generation.audit_full_corpus --count 131072 --workers 4 --reference reference/full_waveform_reference.json
```

This parallel check validates raw files, raw and derived DC-corrected waveforms,
control values, both consolidated manifests and QA flags, then compares all
waveforms against the reference PC's completed corpus. Preserve its output. Full checks
read the entire corpus and take time. A failure must be investigated before
claiming identical reproduction; do not replace local hashes with reference hashes.

Model/feature code must use `generation.corpus_audio.load_audio` to apply the
recorded DC policy and processed float32 underflow policy, rather than treating
raw masters as processed audio. Existing C1/C2/C3 pipelines still need their
full-corpus manifest/adapter integration; generation does not train them.

```python
import pandas as pd
from generation.corpus_audio import load_audio
local = pd.read_parquet("data/raw/corpus_v4/manifest.parquet")
audio, sample_rate = load_audio(local.iloc[0].to_dict(), verify=True)
```

For shared evaluation, agree and save common train/validation/test IDs separately.
Do not create incompatible splits independently on each PC. C1 and C4 human
ratings remain separate datasets that will be joined by the relevant study IDs.

## If you already started with the old runner package

Use the fixed runner/adapter and repair tool included here. For the exact original
single-master recipe, the guarded backed-up migration is:

```powershell
.\venv\Scripts\python.exe -B -u -m generation.repair_corpus_float_policy --count 131072 --apply
```

It verifies every saved file/hash/control row and only updates recipe metadata for
the float32-underflow fix; it never modifies audio/checkpoint rows or starts full
generation. Unrelated recipes are rejected. Already-fixed or fresh runs do not
need this migration. Keep the original recipe and verification report as provenance.
