# SIMULATED C1 main-study responses (`c1_main_sim_v1`)

**No human produced any rating here.** These are engineering fixtures for building
the main-study analysis before real data exist. Do not merge them with approved
responses, count them as participants or report a model trained on them as a C1
result. Replace them with the real export when collection is approved and complete.

## Design

The data follow the dry-run main-study package
(`data/processed/c1_main_v1_simpilot_dryrun/bundle.json`):

- 128 study sounds.
- Blocks 01–30 completed. Each has 3 practice sounds, 22 unique study sounds and 2 hidden repeats, with a break after 12.
- 660 primary evaluations: 108 sounds have 5 listeners and 20 have 6.
- 60 hidden-repeat ratings.
- Two extra sessions (blocks 31 and 32) are excluded: one abandoned and one withdrawn.

## How the data are linked to the simulated pilot

Every "true" rating mean is set by the same artificial rule as the pilot simulation,
on the same scale (`--truth-reference` = the pilot's `simulation_ground_truth.csv`).
Sounds shared with the pilot (16 anchors + 3 practice) keep their pilot truth. Pilot
and main ratings of an anchor therefore differ only by listener and noise, as they
would in a real replication.

## Headline values (seed 20261115)

| Descriptor | ICC(1) | r(sound mean, true mean) | Unclear |
|---|---|---|---|
| Brightness | 0.64 | 0.95 | 1.3% |
| Roughness | 0.50 | 0.90 | 5.6% |
| Percussiveness | 0.66 | 0.94 | 3.1% |
| Sustainedness | 0.62 | 0.93 | 3.9% |

Hidden repeats: median absolute difference 1, and 68% within ±1.

## Files

| File | Contents |
|---|---|
| `c1_main_responses_SIMULATED.csv` | Real C1 export columns plus `source_sample_id`, `label_source`, `generator_version`, `seed` |
| `c1_sessions_SIMULATED.csv` | One row per session, including excluded ones |
| `c1_sound_targets_SIMULATED.csv` | Per sound: mean, median, SD and valid/unclear counts per descriptor (primary ratings only) |
| `simulation_ground_truth.csv` | Hidden rule values: proxies, proxy/true means and 13 parameters. Use for recovery tests only, never as a model input |
| `simulation_listeners.csv` | Hidden listener settings |
| `simulation_summary.json` | Seed, hashes, rule, counts and test–retest summary |

## Regenerate

```powershell
.\venv\Scripts\python.exe -B c1_timbre/simulate_main_ratings.py --overwrite
```

[`simulate_main_ratings.py`](../../simulate_main_ratings.py) runs the pilot simulator
with the main-study defaults. Options: `--seed`, `--participants`, `--output-dir`,
`--plan-version` (use the real plan once it exists) and `--no-incomplete`.

## Replacing with real data

Export the real responses and sessions from the survey backend. Their columns match
`c1_main_responses_SIMULATED.csv`, apart from the four provenance columns at the end.
Point the analysis at the real files. The real export has no ground-truth or listener
files.
