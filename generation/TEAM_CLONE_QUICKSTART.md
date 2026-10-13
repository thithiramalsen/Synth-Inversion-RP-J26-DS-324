# Teammates: clone and reproduce the 131,072-sound dataset

Thithira must first commit/push `generation/prepare_team_clone.py` and this guide
to the branch you will clone. Share the existing `team_v4_131072_SHARE.zip`
privately alongside the repository URL. The ZIP is about 60 MiB and contains
the exact preset, frozen code bytes, pinned requirements, parameter tables and
waveform references. No audio transfer is needed. The preset is excluded from Git.

## Checks on Thithira's original PC

The `reference/` paths below are installed on a **fresh teammate clone** by the
setup command. On Thithira's original completed-dataset PC, the exported reference
files already live in `data/processed/team_handoff_v4_131072/`. Use these paths:

```powershell
.\venv\Scripts\python.exe -B generation/verify_parameter_reference.py --reference data/processed/team_handoff_v4_131072/parameters_full.parquet --manifest data/raw/corpus_v4/manifest.parquet
.\venv\Scripts\python.exe -B -u -m generation.audit_full_corpus --count 131072 --workers 4 --reference data/processed/team_handoff_v4_131072/full_waveform_reference.json
```

The clone setup command is only for fresh clones; it must not be applied to the
original completed-dataset folder. A successful full audio audit takes several
minutes because it reads all 131,072 sounds.

## Message to send to teammates

Use Windows x64 and **Python 3.13.14**, with at least **80 GiB free** on the
drive containing the clone. Download my `team_v4_131072_SHARE.zip` first.
Then follow these steps in PowerShell:

1. Clone the branch containing the setup script:

   ```powershell
   git clone --branch c1-pilot-deployment https://github.com/thithiramalsen/Synth-Inversion-RP-J26-DS-324.git
   cd Synth-Inversion-RP-J26-DS-324
   ```

2. Prepare this **fresh clone** using my ZIP. Change the ZIP path below to your
   actual download location. Run `python --version` first; it must be 3.13.14.

   ```powershell
   python --version
   python -B generation/prepare_team_clone.py --bundle "C:\path\to\team_v4_131072_SHARE.zip" --apply
   python -B generation/verify_reproduction.py --reference reference/clone_integrity.json --stage candidates
   ```

   Setup verifies the ZIP, restores the exact frozen files, installs the preset
   and reference tables, and backs up the tracked pilot metadata. Those metadata
   describe Thithira's original 1,024 WAVs, which are absent from your clone; they
   must not be treated as locally generated audio. Setup generates **no sounds**.
   It refuses existing corpus/audio directories or conflicting uncommitted files.
   Expected changes may appear in Git because frozen source bytes and archived
   reference metadata differ from the checkout. Keep these setup changes local;
   avoid editing, resetting or pulling files, or upgrading dependencies until
   generation and verification finish.

3. Create the environment and install the fixed dependencies:

   ```powershell
   python -m venv venv
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Check first, then generate. Run the second command **only if the check passes**:

   ```powershell
   .\venv\Scripts\python.exe -B -u -m generation.generate_corpus --check --count 131072
   .\venv\Scripts\python.exe -B -u -m generation.generate_corpus --generate --count 131072 --workers 4
   ```

   Your fresh clone renders **all 131,072**, including the same first 1,024
   combinations as Thithira's corpus. A separate 1,024 generation stage is optional
   and not required by this route. Keep the PC powered and prevent sleep. If
   interrupted, rerun the same `--generate` command to resume. Worker count can
   be reduced for a slower PC; it does not change the sample design. If any check
   fails, send the error to Thithira instead of bypassing the check.

5. After completion, verify both labels and audio against my references:

   ```powershell
   .\venv\Scripts\python.exe -B generation/verify_parameter_reference.py --reference reference/parameters_full.parquet --manifest data/raw/corpus_v4/manifest.parquet
   .\venv\Scripts\python.exe -B -u -m generation.audit_full_corpus --count 131072 --workers 4 --reference reference/full_waveform_reference.json
   ```

   Send me both PASS outputs. Same settings give the same parameter design;
   comparing every waveform establishes whether audio samples also match on
   your PC. Differences in WAV header dates and local paths do not affect that
   waveform comparison.

## Output and experiments while rendering

- Audio: `data/raw/corpus_v4/raw_float/`.
- Incremental labels: `data/raw/corpus_v4/chunks/`, committed every 128 sounds.
- Final local labels and audio metadata: `data/raw/corpus_v4/manifest.parquet`.
- Shared labels available immediately: `reference/parameters_normalized.parquet`
  (IDs + 13 normalized targets) and `reference/parameters_full.parquet`
  (also Sobol coordinates, native values and display text).

Join by **sample_id**, not filename sorting. Shared labels allow parameter-space
experiments before all audio finishes; waveform experiments need rendered audio.
Use `generation.corpus_audio.load_audio` to apply the frozen DC conditioning once
when reading a local manifest row. Do not train directly on unconditioned raw
masters. Generation does not produce descriptor ratings, features, trained models
or shared train/validation/test splits; those are separate research steps.
