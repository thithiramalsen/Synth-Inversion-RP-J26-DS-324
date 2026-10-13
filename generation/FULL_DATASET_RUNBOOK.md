# Generate the full v4 corpus: single FLOAT master, four workers

## What to run on the reference PC

The full job has NOT been started. From the repository root:

```powershell
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --check --count 131072
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --generate --count 131072 --workers 4
```

Run the first command before the second. `--check` never renders or writes.
`--generate` automatically resumes; there is deliberately no overwrite flag.
After completion, run the same `--check` again and review the summary's QA flags.

This replaces the earlier full-run recommendation using
`05_generate_pilot_dataset.py --count 131072 --resume`. That historical generator
remains unchanged for reproducibility, but writes two WAV copies sequentially.
`preflight_dataset.py` also checks that OLD two-copy workflow. Use the new module's
`--check` for the single-master workflow.

## What stays the same

Profile: `restricted_bend_sustain_v4`, 13 controls, Basic Shapes oscillator,
Bend plus filter-envelope sustain, note 60, velocity 0.8, mono 44,100 Hz,
1.5-second note, 3-second recording, scrambled Sobol seed 20260803. The parameter
order, ranges, preset, Vita 0.0.5 and other pinned dependencies stay unchanged.
Every worker creates a fresh synth for each sound, exactly as the frozen renderer
did. No shortening, resampling, gain normalization or PCM16 conversion is added.

The current 1,024 v4 sounds are reused by reference; no original WAV or manifest
is modified, moved or deleted. The old eight-control `pilot_v1` set is unrelated.
The fixed survey sounds, bundles, participant responses and invitations are unchanged.
The target 131,072 includes the current 1,024: **130,048 additional sounds**.

## Storage and audio access

New sounds have one raw FLOAT WAV. DC correction is applied once in memory when
needed, then rounded to float32 just as the historical processed FLOAT WAV was.
Both raw and processed sample hashes are recorded. The storage policy is
`raw_float_dc_on_read_v1`; the synthesis and DC policy remain the original v4.

The full raw audio payload is about **64.6 GiB**. Existing processed copies for
only the first 1,024 remain untouched (about another 0.5 GiB). New generation needs
about **74.6 GiB free including conservative headers and 10 GiB working headroom**.
The reference PC had 95.6 GiB free on D: at the 13 October check. Feature caches,
training artifacts and backups require additional space.

Output files:

- `data/raw/corpus_v4/raw_float/`: new raw masters, using original stable v4 IDs.
- `data/raw/corpus_v4/recipe.json`: frozen synthesis/runtime/runner fingerprints.
- `data/raw/corpus_v4/chunks/*.json`: authoritative incremental metadata checkpoints.
- `data/raw/corpus_v4/manifest.csv` and `.parquet`: consolidated tables after completion.
- `data/raw/corpus_v4/summary.json`: completed count, speed and QA totals.

Imported rows point to their original raw files in
`data/raw/audio/restricted_bend_sustain_v4/raw_float/`. Keep that folder and its
existing manifests. This is not a new set of parameter combinations; it is a
new storage/runner layout for the same corpus.

**Model/feature code must use the audio adapter, not play/train directly on raw paths:**

```python
import pandas as pd
from generation.corpus_audio import load_audio

rows = pd.read_parquet("data/raw/corpus_v4/manifest.parquet")
audio, sample_rate = load_audio(rows.iloc[0].to_dict(), verify=True)
# audio is canonical DC-corrected mono float32, ready for feature extraction.
```

There is intentionally no misleading `audio_path` column pointing to raw audio.
Existing C1/C2/C3 scripts expecting the older processed-WAV manifest are NOT
silently switched to this schema. Integrate this adapter when building their
full-corpus feature/training stages; do not merely rename raw_audio_path to audio_path.
Precompute features once if repeated DC processing per training epoch is unwanted.
You need not create a second permanent 64.6 GiB audio directory to do that.

## Speed and evidence

On 13 October 2026, the reference i7-13650HX PC rerendered 32 existing sounds at
spread-out indices in memory for each configuration:

| Worker processes | Seconds for 32 | Sounds/second |
|---|---:|---:|
| 1 | 8.37 | 3.82 |
| 4 | 4.20 | 7.62 |
| 8 | 4.25 | 7.54 |

All 96 test results matched the reference raw samples, processed samples and
numeric control values exactly. No benchmark WAV files were written. All 1,024
historical processed files were also reconstructed exactly from their raw masters.
The benchmark includes process startup, but excludes file writes/checkpoints and
long-run thermal throttling. At 7.62/s, 130,048 renders would take about 4.7 hours;
allow longer in practice. Do not promise the same speed on teammates' PCs.

Run a local benchmark after a verified prefix exists:

```powershell
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --benchmark
```

It rerenders 32 existing sounds with 1, 4 and 8 workers in memory. It never starts
full generation. Keep the PC powered and prevent sleep during the real job.
Worker count can change on resume; the synthesis recipe cannot.

## Stops, crashes and validation

One coordinator writes files in Sobol order. An OS lock blocks a second writer
against the same folder. Work queues are bounded; all 131,072 audio arrays are
never held in memory. Metadata checkpoints every 128 new sounds, and a controlled
stop attempts to commit successfully written pending rows.

Rerun the SAME `--generate` command after interruption. A hard crash may leave
uncheckpointed raw WAVs. The runner rerenders those indices and adopts existing
files only if their samples match exactly; it never overwrites a conflicting WAV.
Temporary `.tmp` files from a hard crash are not committed audio and are ignored;
inspect/archive them if they accumulate. Do not bypass recipe/hash checks or
manually change IDs to make a resume proceed. If a saved file differs, stop and
investigate. Flat CSV/Parquet exports may be absent/stale during an interrupted
run; checkpoint JSON chunks are authoritative until completion.

Eight focused tests cover corruption rejection, writer exclusion, prefix import
interruption, stop/resume, orphan comparison and adoption, preservation of saved
files, target validation and reference checking. No Vital audio was generated by
those tests; they use temporary numerical fixtures. An interrupted write due to
actual power/hardware failure can still require recovery from backup.

## Teammates: exact shared recipe, independent generation

Privately share:
`data/processed/candidate_reproduction_v4/candidate_recipe_v4_parallel_single_master.zip`.
The small ZIP includes the exact preset (with embedded wavetable), frozen generator,
pinned requirements, original reference, new runner, adapter and this guide. Git
alone is insufficient because the required preset is ignored. The package has no
audio, participant responses, invitation codes or credentials.

1. Extract into a NEW folder with at least 80 GiB free for generation; allow more
   for features/training. Use Windows x64 and **Python 3.13.14** matching the
   recorded runtime. With `python` pointing to that interpreter:

   ```powershell
   python -m venv venv
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   .\venv\Scripts\python.exe -B -u -m generation.generate_corpus --check
   ```

2. First reproduce the original 1,024 with the frozen generator and compare ALL
   their raw/processed waveform bytes and recipe files:

   ```powershell
   .\venv\Scripts\python.exe -B -u generation/scripts/05_generate_pilot_dataset.py --profile restricted_bend_sustain_v4 --count 1024
   .\venv\Scripts\python.exe -B generation/verify_reproduction.py --reference reference/reference.json --stage candidates
   ```

   Do not copy `reference/*.csv` into `data/manifests` before generation. Local
   generation creates its own file hashes. Do not recreate the preset by hand,
   change dependencies, or upgrade Vita to enable a different concurrency method.
   Installation and equality on other PCs are not yet verified; these checks
   detect differences rather than assuming every machine will be identical.

3. Run the new runner's `--check` and `--benchmark`, then the `--generate` command
   above with the worker count that works best locally. It imports that prefix
   and generates only the remaining rows as single raw masters.

The newer runner and adapter have their own integrity fingerprints in the package
reference; the original recipe reference remains unchanged. The package README
has a command to verify these extra files before starting.

## Compare full corpora without sharing audio

After the reference PC completes and verifies the full corpus:

```powershell
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --count 131072 --export-reference data/processed/v4_full_waveforms.json
```

This writes hashes keyed by stable sample ID, independent of machine paths and
WAV header timestamps. It verifies raw files and derived processed samples first.
Share that JSON with teammates. After their own complete run:

```powershell
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --count 131072 --verify-reference PATH_TO_SHARED_JSON
```

Only a successful full comparison establishes equality across the full generated
corpora. Matching the initial 1,024 is a compatibility gate, not proof for later
samples. Whole-WAV hashes can differ because of header timestamps; each PC keeps
its own whole-file hashes for local integrity. The exported waveform hashes avoid
that timestamp issue. Full checks read the entire corpus and take time.

## Research decisions before training

Human ratings need not finish before generation. Later survey subset changes do
not require rerendering. Changes to actual bounds, controls, note, wavetable or
processing require a new version. Historical provisional wording in the frozen
config remains unchanged; the explicit DC policy is already recorded.

Agree and save shared train/validation/test IDs, including how development-used
study sounds and near-duplicate/alternative patches are handled. Use the same
canonical processing for training, inference and diagnostic perturbations.
C1's quiet-frame feature-definition issue remains separate. FLOAT storage does
not fix that issue; it preserves original data for later feature improvements.
131,072 is a planned sample count, not evidence of exhaustive 13-dimensional
coverage or sufficient model accuracy. Use learning curves and held-out evaluation.
