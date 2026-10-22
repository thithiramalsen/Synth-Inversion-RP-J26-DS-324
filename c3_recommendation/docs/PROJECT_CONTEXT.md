# C3 project context (for Claude chats in the RESEARCH project)

Status as of 22 Oct 2026. Source of truth: `c3_recommendation/docs/DECISIONS.md` (D-001 … D-022),
`DATA_CONTRACT.md`, and outputs under `c3_recommendation/outputs/v4/` (git-ignored).

## Who and what
- Researcher: D.A.V.P. Waidyarathne (IT23208780). Project J26-DS-324 "Uncertainty-Aware
  Audio-to-Synth Inversion with Perceptual Patch Recommendation". Component **C3**.
- C3 = diversity-aware set-level patch recommendation: for a target synth sound, return k = 5
  patches that **sound close** (relevance in audio space) but use **different knob settings**
  (redundancy in parameter space), via MMR re-ranking of an audio-retrieved shortlist.
- Research question: can MMR give sets with significantly lower parameter redundancy than
  similarity-only top-k while keeping comparable relevance?
  H1 diversity (mean + minimum pairwise parameter distance), H2 relevance loss ≤ τ = 2%,
  H3 human usefulness (study).
- Teammates: C1 timbre descriptors, C2 parameter estimation + uncertainty (Malsen built the
  shared survey service), C4 human-aligned similarity metric (uses CLAP). C3 does not depend
  on them; C4's metric can plug in as the relevance function later.

## Data
- Corpus v4: 131,072 Vital sounds, scrambled Sobol (seed 20260803), 13 continuous controls,
  MIDI 60, velocity 0.8, 3.0 s mono 44.1 kHz, raw float WAV + 10 Hz DC high-pass on read.
- Audio: `data/raw/corpus_v4/raw_float/<sample_id>.wav`; parameters + hashes:
  `data/raw/corpus_v4/manifest.parquet`. Teammate reference copy in `reference/`.
- Parameters scaled to 0–1 slider positions: (normalized − min)/(max − min). Distance =
  Euclidean / √13 on slider positions.
- Audio gate passed 8/8 (identical to reference, official waveform comparison PASS).
- Frozen split (seed 20261014): bank 104,858 / val 13,107 / test 13,107; test locked in code
  until `docs/PREREGISTRATION.md` exists and `final_test.enabled: true`.

## Code (`c3_recommendation/`)
- Package `src/c3/`: config, schema, param_space, data_sources, audio_io, splits, relevance,
  retrieval, selection (top-k, MMR, random), metrics, evaluate, stats, analysis, features,
  tuning, demo, runinfo. Legacy `pipeline.py` (pilot_v1) untouched.
- Scripts `scripts/00…07_*.py`, `demo_build_viewer.py`, `demo_test_lock.py`.
- Tests `tests_v4/` — 323 passing.
- Human study `human_study/` (FastAPI + SQLite, local rehearsal only, research collection disabled).

## Results so far (validation only — not final)
- Bank structure: median 1-NN parameter distance 0.129, random pair 0.403 → no natural
  near-duplicates; dup_rate is uninformative for H1 (reported descriptively).
- Features: mfcc26 (identical to pilot MFCC) and logmel_stats; diagnostic indistinguishable
  (target→audio top-1 parameter distance 0.308 vs 0.306; random patch 0.40).
- Phase 7 (500 val targets, rules fixed before running, D-017): **mfcc26, N = 100, k = 5,
  λ = 0.5**. Top-k → C3: relevance 0.9725 → 0.9550 (loss 1.81%, CI upper 1.90%), mean pairwise
  parameter distance 0.325 → 0.416 (+28%), minimum pair 0.226 → 0.362 (+60%). Random from
  shortlist: loss 3.80%, distance 0.340. τ = 1% would pick λ 0.7; τ = 5% λ 0.4.
- Log-mel secondary: λ 0.4 (grid edge). CLAP planned (laion/clap-htsat-unfused, revision
  8fa0f1c6…, same as C4), not yet extracted.

## Human study (H3), version c3-human-v2
- Blinded Set A / Set B (top-5 vs C3), 8 validation cases + practice, knob bars shown, target
  knobs hidden; 12 completions planned (cap 16); counterbalanced (C3 as A in 4/8 cases).
- Per-sound closeness 1–5; three set questions (useful starting points, closer overall, more
  different by ear); confidence; reason. Headphone check (Woods et al. 2017 style), ≥ 5/6,
  max 3 attempts. `--demo` mode allows skipping it (port 8768); skipped sessions excluded.
- Primary outcome (D-020): per participant C3-only minus top-k-only closeness; "heard as close"
  if 95% bootstrap CI lower bound > −0.5. Needs ethics approval before real participants.

## Open items
1. User writes and commits `docs/PREREGISTRATION.md` (template in `PREREGISTRATION_TEMPLATE.md`).
2. Phase 8 final test (1,000 test targets, Wilcoxon, bootstrap, Holm) — after step 1.
3. CLAP features (needs torch cu118 + transformers 4.50.0), Phase 9 divergence, Phase 10 API/CLI.
4. Check 4 `data/manifests/` files deleted in commit 8f7a6ad with the team.

## Working conventions
- Build step by step; ask before each next step. The user runs every git commit personally,
  one commit per file or small piece, with descriptive messages.
- Never invent results; validation numbers are labelled as such; the test split stays locked.
