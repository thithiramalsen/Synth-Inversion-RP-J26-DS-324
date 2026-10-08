# C1 candidate generation and selection 7 October 2026

The researcher explicitly authorized the new 1,024-sound pool and selection.
Generation and selection are complete; participant recruitment remains closed.

## Result

- Dataset: `restricted_bend_sustain_v4`, 13 controls, one oscillator, fixed Basic
  Shapes wavetable asset, MIDI 60, velocity 0.8, 44.1 kHz mono, 1.5-second note,
  3-second render, Sobol seed 20260803.
- 1,024 candidates generated in 294.45 seconds (3.48 sounds/second).
- All 1,024 passed the implemented technical eligibility checks. No exclusions.
- 64 unique study sounds and 3 disjoint practice sounds selected using the existing
  parameter/acoustic diversity heuristic. This does not establish complete
  parameter-interaction coverage or perceptual descriptor coverage.
- Sixteen assignments, each 32 primary sounds + 4 hidden repeats + 3 practice;
  eight primary listener assignments per study sound. Actual replication still
  depends on completed sessions.
- Selected playback target: -27.986 dBFS note-on RMS, with gains from -14.413 to
  +14.160 dB and peak ceiling 0.89. No compression/fades. Listen particularly to
  these gain extremes; equal RMS does not guarantee equal perceived loudness.

## Files and validation

- `data/manifests/restricted_bend_sustain_v4.csv`: candidate parameters, paths,
  audio QA and full-file hashes; accompanying config, summary and Parquet saved.
- `data/raw/audio/restricted_bend_sustain_v4/`: DC-filtered FLOAT WAVs, with original
  FLOAT renders retained under `raw_float/`.
- `data/processed/c1_pilot_v1/bundle.json`: frozen copied selection, processing,
  assignments and hashes. Do not rebuild/overwrite after participant use.
- `selected_sounds.csv`, `parameter_ranges.csv`, `verification.json` and `QA.md`
  in that bundle directory describe the selection and audit.
- Twenty-one generation tests passed before rendering. Preparation verified raw
  and processed source hashes, formats and technical eligibility.
- Three sampled candidates (indexes 0, 511, 1023) were independently rerendered:
  raw and DC-filtered float samples matched exactly on this machine.
- Verified the current 1,024 parameter vectors are exactly the initial prefix of
  the 131,072-point sequence under the same seed/configuration.
- Checked the assignment counts, repeat separation and PCM16 playback versus
  FLOAT feature-signal quantization. Original engineering/rehearsal data preserved.

## Extending to 131072

Human ratings are not required to render the synthetic corpus. It may be generated
in parallel with the study once its architecture, ranges, note settings and storage
policy are accepted. Pilot findings can still justify changes to that domain;
changed bounds/preset require a new version rather than relabelling old audio.
Descriptor wording changes alone need not invalidate the raw synth corpus.

With the unchanged v4 recipe, `--count 131072 --resume` adds 130,048 sounds and
preserves the original 1,024 after verifying hashes and configuration. The copied
pilot bundle and the small reproduction reference remain frozen. At the observed
speed, the extra rendering alone projects to approximately 10.4 hours; this is an
estimate, not a scheduled or started job.

Current files: original eight-control pilot WAVs are 16-bit PCM; new v4 raw and
DC-only artifacts are 32-bit FLOAT; participant playback is 16-bit PCM.
For 131,072 three-second mono 44.1 kHz WAVs, sample payload sizes are approximately:

| Storage policy | Payload size |
|---|---:|
| One 16-bit PCM copy | 32.3 GiB |
| One 32-bit FLOAT copy | 64.6 GiB |
| Raw + DC-filtered FLOAT copies | 129.2 GiB |

Headers, manifests, features, temporary files and backups are additional.
D: had about 97 GiB free before this run. The existing two-copy large-corpus policy
will not fit. A versioned alternative could retain raw FLOAT plus reproducible
on-demand filtering, or add other storage; do not silently discard raw evidence
or change the established v4 generator during an extension.

## Teammate reproduction

`data/processed/candidate_reproduction_v4/candidate_recipe_v4_1024.zip` contains
an exact source/preset snapshot, pinned package requirements, reference manifest,
selection table and the waveform checker. It is approximately 0.85 MiB and contains
no audio, participant data, invitations or credentials.

Extract to a new folder, match the recorded Windows/Python/package environment,
then follow its README. The reference checks 2,202 recipe/audio entries. Exact
sample reproduction across other platforms or binary builds is not guaranteed;
verify it rather than assuming it. A different result must be investigated.

FLOAT WAV PEAK headers include creation timestamps, so their whole-file hashes
can differ even if every sample is identical. The checker compares exact format
and audio sample bytes, ignoring header timestamps. Generated local manifests
and bundles correctly retain each machine's own whole-file hashes. Do not replace
these with another machine's hashes. Machine paths and creation times also differ.

## Next step

Audition the selected, level-controlled clips (including gain extremes), complete
the participant information/eligibility and actual ethics outcome, and rehearse
through the deployed full-length survey before recruiting. These steps have not
been marked complete by automated audio QA. The 131,072 extension was not started.
