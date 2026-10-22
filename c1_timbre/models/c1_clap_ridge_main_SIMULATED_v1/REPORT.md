# CLAP + ridge vs 19-feature ridge (c1_clap_ridge_main_SIMULATED_v1)

> **SIMULATED labels: engineering check of the software, not perceptual evidence** The comparison tests the software, not which representation predicts real listeners.

CLAP `laion/clap-htsat-unfused` @ `8fa0f1c6d0` (same pin as C4), 512-d embedding of the level-matched FLOAT copy of the heard signal, 48 kHz, L2-normalized. Same targets, held-out split (102 train / 26 test) and 20×5-fold CV folds for every model; ridge α chosen inside training folds.

| Descriptor | Model | Inputs | Test MAE | Baseline | Test R² | CV R² (95% range) | Ceiling share |
|---|---|---|---|---|---|---|---|
| brightness | features19 | 19 | 0.43 | 1.03 | 0.80 | 0.77 (0.74–0.79) | 93% |
| brightness | clap512 | 512 | 0.52 | 1.03 | 0.74 | 0.75 (0.73–0.77) | 91% |
| brightness | combined | 35 | 0.41 | 1.03 | 0.80 | 0.78 (0.76–0.80) | 93% |
| roughness | features19 | 19 | 0.57 | 1.16 | 0.78 | 0.64 (0.60–0.69) | 88% |
| roughness | clap512 | 512 | 0.84 | 1.16 | 0.42 | 0.26 (0.19–0.31) | 57% |
| roughness | combined | 35 | 0.60 | 1.16 | 0.74 | 0.64 (0.60–0.67) | 87% |
| percussiveness | features19 | 19 | 0.48 | 1.11 | 0.77 | 0.80 (0.77–0.82) | 94% |
| percussiveness | clap512 | 512 | 0.68 | 1.11 | 0.55 | 0.57 (0.51–0.60) | 78% |
| percussiveness | combined | 35 | 0.53 | 1.11 | 0.72 | 0.76 (0.72–0.79) | 91% |
| sustainedness | features19 | 19 | 0.56 | 1.10 | 0.76 | 0.77 (0.74–0.78) | 93% |
| sustainedness | clap512 | 512 | 0.76 | 1.10 | 0.51 | 0.64 (0.61–0.66) | 85% |
| sustainedness | combined | 35 | 0.60 | 1.10 | 0.69 | 0.73 (0.72–0.75) | 91% |

## Paired comparison on identical folds

Positive MAE improvement = the alternative has lower error than the 19-feature ridge.

| Descriptor | Alternative | MAE improvement (95% range) | Repeats better | R² gain | CLAP permutation p |
|---|---|---|---|---|---|
| brightness | clap512 | -0.036 (-0.066 to +0.002) | 10% | -0.027 | 0.005 |
| brightness | combined | +0.010 (-0.016 to +0.046) | 70% | +0.005 |  |
| roughness | clap512 | -0.321 (-0.386 to -0.271) | 0% | -0.378 | 0.005 |
| roughness | combined | -0.016 (-0.040 to +0.002) | 10% | -0.007 |  |
| percussiveness | clap512 | -0.256 (-0.299 to -0.226) | 0% | -0.235 | 0.005 |
| percussiveness | combined | -0.054 (-0.097 to -0.021) | 0% | -0.039 |  |
| sustainedness | clap512 | -0.132 (-0.176 to -0.084) | 0% | -0.128 | 0.005 |
| sustainedness | combined | -0.030 (-0.062 to +0.009) | 5% | -0.032 |  |

## Reading this

- Prefer CLAP only if it beats the 19 features in most repeats and its improvement range excludes 0; otherwise keep the
  interpretable 19-feature ridge as the main model.
- CLAP dimensions have no individual meaning: no construct-validity check is possible, and control effects through CLAP
  must be checked for smoothness before use.
- `model_final_all_sounds.json` holds the CLAP ridge trained on all sounds (inputs `clap_000…clap_511`).
