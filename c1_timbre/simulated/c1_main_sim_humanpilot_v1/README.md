# SIMULATED C1 main-study responses from the human pilot (`c1_main_sim_humanpilot_v1`)

**No human produced any rating in this folder.** The main study has not been run. These
ratings are simulated so that the main-study analysis and model can be built before real
data exist. Do not report a model trained on them as a C1 result.

## What is real and what is simulated

| Part | Source |
|---|---|
| Pilot ratings | **Human.** 27 complete sessions, 540 ratings, 64 sounds (`c1_timbre/pilot_data/genuine_v1`) |
| Main-study sound set and assignments | Planned from the human pilot (`c1_timbre/main_study/c1_main_v1_humanpilot`) |
| "True" sound means | 16 anchors: observed human pilot means. Other sounds: pilot-trained ridge prediction plus a sound-level deviation (`main_truth_from_pilot.csv`) |
| Listener behaviour | Calibrated to the human pilot: listener offset SD 0.74; rating noise SD 0.79 / 0.96 / 1.15 / 1.21 (B/R/P/S); no "cannot judge" answers |
| Main-study ratings | **Simulated** |

## Design

- 30 completed sessions: 3 practice + 30 unique study sounds + 2 hidden repeats each.
- 900 primary evaluations; each of the 128 sounds has 7–8 listeners.
- One abandoned and one withdrawn session are included and excluded from analysis.

## Regenerate

```powershell
.\venv\Scripts\python.exe -B -m c1_timbre.build_pilot_dataset --exports "<Downloads>/c1-responses (2).csv" "<Downloads>/c1-responses (3).csv" --output-dir c1_timbre/pilot_data/genuine_v1
.\venv\Scripts\python.exe -B -m c1_timbre.plan_main_study --pilot-responses c1_timbre/pilot_data/genuine_v1/c1_pilot_responses.csv --sessions-from-responses --allow-mixed-versions --version c1_main_v1_humanpilot
.\venv\Scripts\python.exe -B -m c1_timbre.truth_from_pilot --pilot-responses c1_timbre/pilot_data/genuine_v1/c1_pilot_responses.csv --pilot-bundle survey/deploy/study/bundle.json --plan-version c1_main_v1_humanpilot --output c1_timbre/pilot_data/genuine_v1/main_truth_from_pilot.csv
.\venv\Scripts\python.exe -B c1_timbre/simulate_pilot_ratings.py --bundle data/processed/c1_main_v1_humanpilot/bundle.json --config c1_timbre/main_study/c1_main_v1_humanpilot/c1_main_protocol_DRAFT.json --output-dir c1_timbre/simulated/c1_main_sim_humanpilot_v1 --participants 30 --seed 20261115 --start-date 2027-01-11T09:00:00+00:00 --study-id c1_main_SIMULATED_humanpilot_v1 --generator-version c1_main_sim_humanpilot_v1 --file-prefix c1_main --truth-means c1_timbre/pilot_data/genuine_v1/main_truth_from_pilot.csv --noise-sd 0.79 0.96 1.15 1.21 --bias-sd 0.74 --unclear-scale 0 --no-confusions
.\venv\Scripts\python.exe -B -m c1_timbre.train_c1_model --responses c1_timbre/simulated/c1_main_sim_humanpilot_v1/c1_main_responses_SIMULATED.csv --bundle data/processed/c1_main_v1_humanpilot/bundle.json --ground-truth c1_timbre/simulated/c1_main_sim_humanpilot_v1/simulation_ground_truth.csv --run-name c1_ridge_main_SIMULATED_humanpilot_v1
.\venv\Scripts\python.exe -B -m c1_timbre.train_c1_clap --base-run c1_timbre/models/c1_ridge_main_SIMULATED_humanpilot_v1
.\venv\Scripts\python.exe -B -m c1_timbre.build_predicted_dataset --model-run c1_timbre/models/c1_ridge_main_SIMULATED_humanpilot_v1
.\venv\Scripts\python.exe -B -m c1_timbre.control_effects --model-run c1_timbre/models/c1_ridge_main_SIMULATED_humanpilot_v1
```

Replace this folder with the real main-study export once collection is approved and complete.
