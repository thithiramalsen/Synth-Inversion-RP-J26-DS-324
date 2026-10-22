# CLAP + ridge vs 19-feature ridge (c1_clap_ridge_main_SIMULATED_humanpilot_v1)

> **SIMULATED labels: engineering check of the software, not perceptual evidence** The comparison tests the software, not which representation predicts real listeners.

CLAP `laion/clap-htsat-unfused` @ `8fa0f1c6d0` (same pin as C4), 512-d embedding of the level-matched FLOAT copy of the heard signal, 48 kHz, L2-normalized. Same targets, held-out split (102 train / 26 test) and 20×5-fold CV folds for every model; ridge α chosen inside training folds.

| Descriptor | Model | Inputs | Test MAE | Baseline | Test R² | CV R² (95% range) | Ceiling share |
|---|---|---|---|---|---|---|---|
| brightness | features19 | 19 | 0.52 | 1.29 | 0.83 | 0.79 (0.76–0.80) | – |
| brightness | clap512 | 512 | 0.62 | 1.29 | 0.78 | 0.74 (0.71–0.75) | – |
| brightness | combined | 35 | 0.53 | 1.29 | 0.82 | 0.77 (0.75–0.79) | – |
| roughness | features19 | 19 | 0.73 | 1.18 | 0.63 | 0.68 (0.66–0.70) | – |
| roughness | clap512 | 512 | 0.73 | 1.18 | 0.64 | 0.62 (0.59–0.64) | – |
| roughness | combined | 35 | 0.70 | 1.18 | 0.65 | 0.65 (0.61–0.67) | – |
| percussiveness | features19 | 19 | 0.69 | 0.85 | 0.40 | 0.49 (0.47–0.51) | – |
| percussiveness | clap512 | 512 | 0.83 | 0.85 | 0.13 | 0.28 (0.21–0.33) | – |
| percussiveness | combined | 35 | 0.70 | 0.85 | 0.40 | 0.43 (0.38–0.48) | – |
| sustainedness | features19 | 19 | 0.58 | 0.62 | 0.16 | 0.25 (0.20–0.28) | – |
| sustainedness | clap512 | 512 | 0.62 | 0.62 | 0.01 | 0.14 (0.10–0.18) | – |
| sustainedness | combined | 35 | 0.64 | 0.62 | 0.02 | 0.23 (0.19–0.27) | – |

## Paired comparison on identical folds

Positive MAE improvement = the alternative has lower error than the 19-feature ridge.

| Descriptor | Alternative | MAE improvement (95% range) | Repeats better | R² gain | CLAP permutation p |
|---|---|---|---|---|---|
| brightness | clap512 | -0.074 (-0.104 to -0.050) | 0% | -0.051 | 0.005 |
| brightness | combined | -0.021 (-0.039 to +0.001) | 5% | -0.014 |  |
| roughness | clap512 | -0.063 (-0.094 to -0.032) | 0% | -0.058 | 0.005 |
| roughness | combined | -0.030 (-0.062 to -0.004) | 0% | -0.029 |  |
| percussiveness | clap512 | -0.141 (-0.169 to -0.115) | 0% | -0.217 | 0.005 |
| percussiveness | combined | -0.052 (-0.075 to -0.028) | 0% | -0.063 |  |
| sustainedness | clap512 | -0.028 (-0.061 to -0.004) | 0% | -0.107 | 0.005 |
| sustainedness | combined | +0.002 (-0.025 to +0.017) | 65% | -0.016 |  |

## Reading this

- Prefer CLAP only if it beats the 19 features in most repeats and its improvement range excludes 0; otherwise keep the
  interpretable 19-feature ridge as the main model.
- CLAP dimensions have no individual meaning: no construct-validity check is possible, and control effects through CLAP
  must be checked for smoothness before use.
- `model_final_all_sounds.json` holds the CLAP ridge trained on all sounds (inputs `clap_000…clap_511`).
