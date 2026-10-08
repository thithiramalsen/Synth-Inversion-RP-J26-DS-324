"""Diagnostic follow-up to audit_pcm_precision; does not alter production features."""
from __future__ import annotations

import os
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generation.audit_pcm_precision import encode, rms, db, describe, sha, feature_summary, retrieval_summary, FEATURES
from c1_timbre.feature_extraction import extract_features, frame_audio
from c3_recommendation import pipeline as c3


def main():
    folder = ROOT / "generation/characterization/pcm_precision_v1"
    output = folder / "feature_diagnosis.json"
    if output.exists():
        raise FileExistsError(output)
    old = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    manifest = ROOT / "data/manifests/restricted_bend_sustain_v4.csv"
    bundle_path = ROOT / "data/processed/c1_pilot_v1/bundle.json"
    assert sha(manifest) == old['manifest_sha256'] and sha(bundle_path) == old['bundle_sha256']
    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    settings = c3.feature_settings({"sample_rate": 44100})
    bank = c3.mel_filterbank(44100, 2048, settings['n_mels'], settings['f_min_hz'], settings['f_max_hz'])
    basis = c3.dct_basis(13, settings['n_mels'])
    window = np.hanning(2048)
    frequency = np.fft.rfftfreq(2048, 1/44100)
    floor_features = {'float': [], 'pcm16_current': []}
    centroid_records, full_gain = [], []
    worst_frames = None
    worst_id = 'restricted_bend_sustain_v4_01015'
    for index, row in enumerate(rows):
        path = ROOT / row['audio_path']
        assert sha(path) == row['audio_sha256']
        audio, rate = sf.read(path)
        pcm = encode(audio)
        gain = bundle['level_policy']['target_rms'] / rms(audio[:66150])
        full_gain.append({'sample_id': row['sample_id'], 'gain_db': db(gain),
                          'result_peak': float(np.max(np.abs(audio))*gain),
                          'error_rms_dbfs': db(rms((pcm-audio)*gain))})
        frames = frame_audio(audio, 2048, 512)
        frame_levels = np.sqrt(np.mean(frames**2, axis=1))
        centroids = []
        for name, wave in (('float', audio), ('pcm16_current', pcm)):
            # Exactly C3's FFT, mel bank and DCT, changing ONLY the power floor
            # from 1e-12 to 1e-8, the existing C2 80 dB floor. Diagnostic, not tuned
            # to participant labels, and not installed into C3.
            padded = np.pad(wave, 1024, mode='reflect')
            mf = np.lib.stride_tricks.sliding_window_view(padded, 2048)[::512]
            power = (np.abs(np.fft.rfft(mf*window, axis=1))/(window.sum()/2))**2
            coeff = np.log(np.maximum(power @ bank.T, 1e-8)) @ basis.T
            floor_features[name].append(np.r_[coeff.mean(axis=0), coeff.std(axis=0)])
            spectrum = np.abs(np.fft.rfft(frame_audio(wave, 2048, 512)*window, axis=1))
            total = spectrum.sum(axis=1)
            values = np.zeros(len(total))
            valid = total > np.finfo(float).eps
            values[valid] = spectrum[valid] @ frequency / total[valid]
            centroids.append(values)
        difference = centroids[1]-centroids[0]
        quiet = frame_levels < .001  # -60 dBFS RMS: diagnostic only
        centroid_records.append({'sample_id': row['sample_id'],
                                 'full_mean_centroid_shift_hz': float(difference.mean()),
                                 'contribution_from_frames_below_minus60dbfs_hz': float(np.sum(difference[quiet])/len(difference)),
                                 'contribution_from_other_frames_hz': float(np.sum(difference[~quiet])/len(difference))})
        if row['sample_id'] == worst_id:
            worst_frames = (centroids, frame_levels)
        if (index+1) % 256 == 0:
            print(f"Diagnosed {index+1}/{len(rows)}", flush=True)

    ff = np.asarray(floor_features['float'])
    fq = np.asarray(floor_features['pcm16_current'])
    actual_float, actual_playback = [], []
    for sample in bundle['samples'].values():
        a = bundle_path.parent / sample['feature_path']
        b = bundle_path.parent / sample['playback_path']
        assert sha(a) == sample['feature_sha256'] and sha(b) == sample['playback_sha256']
        x, _ = sf.read(a); y, _ = sf.read(b)
        actual_float.append(list(extract_features(x, 44100, 2048, 512).values()))
        actual_playback.append(list(extract_features(y, 44100, 2048, 512).values()))
    result = {'audit_summary_sha256': sha(folder/'summary.json'), 'script_sha256': sha(__file__),
              'scope': 'Diagnostic only. Existing C1/C2/C3 implementations, audio and bundle unchanged.',
              'c3_floor_only_change': {'original_power_floor': 1e-12, 'diagnostic_power_floor': 1e-8,
                                      'reason': 'Pre-existing C2 uses an 80 dB floor; no listener labels used.',
                                      'feature_changes': feature_summary(ff, fq, c3.feature_names(13)),
                                      'retrieval': retrieval_summary(ff, fq)},
              'actual_67_study_float_feature_files_vs_existing_pcm16_playback': feature_summary(np.asarray(actual_float), np.asarray(actual_playback), FEATURES),
              'full_pool_matched_to_current_study_target': {
                  'warning': 'Hypothetical fixed-target calculation, not a replacement gain policy. Clips above 0.89 need a revised group target or exclusion; no clipping is applied here.',
                  'target_dbfs': bundle['level_policy']['target_dbfs'],
                  'gain_db': describe([r['gain_db'] for r in full_gain]),
                  'encoding_error_after_gain_dbfs': describe([r['error_rms_dbfs'] for r in full_gain]),
                  'clips_above_0p89_peak': sum(r['result_peak'] > .89+1e-8 for r in full_gain),
                  'clips_above_full_scale': sum(r['result_peak'] >= 1 for r in full_gain)},
              'worst_full_centroid_case': next(r for r in centroid_records if r['sample_id']==worst_id)}
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    for filename, entries in [('centroid_frame_diagnosis.csv', centroid_records), ('full_pool_gain_diagnosis.csv', full_gain)]:
        with (folder/filename).open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(entries[0])); writer.writeheader(); writer.writerows(entries)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    centroids, levels = worst_frames
    times = (np.arange(len(levels))*512+1024)/44100
    axes[0,0].plot(times, 20*np.log10(np.maximum(levels, 1e-15)), color='#34495e')
    axes[0,0].axhline(-60, color='#b9770e', linestyle='--', label='Diagnostic -60 dBFS line')
    axes[0,0].set(title='Example 01015: frame level', xlabel='Time (s)', ylabel='RMS dBFS', ylim=(-160, 0)); axes[0,0].legend(fontsize=8)
    axes[0,1].plot(times, centroids[0], label='FLOAT', alpha=.8)
    axes[0,1].plot(times, centroids[1], label='Current PCM16', alpha=.8)
    axes[0,1].set(title='Same clip: existing C1 frame centroid', xlabel='Time (s)', ylabel='Hz'); axes[0,1].legend(fontsize=8)
    methods = ['pcm16_current', 'pcm16_nearest', 'pcm24_current']
    errors = list(csv.DictReader((folder/'waveform_errors.csv').open(encoding='utf-8')))
    for name in methods:
        values = sorted(float(r['c2_rmse_db']) for r in errors if r['method']==name)
        axes[1,0].plot(values, np.arange(1, len(values)+1)/len(values), label=name)
    axes[1,0].set(title='Existing C2 log-mel changes: all 1,024 clips', xlabel='Per-clip RMSE (dB)', ylabel='Fraction of clips'); axes[1,0].legend(fontsize=8)
    bars = [old['methods'][m]['c3_retrieval']['top1_agreement_fraction']*100 for m in methods]
    bars += [result['c3_floor_only_change']['retrieval']['top1_agreement_fraction']*100]
    axes[1,1].bar(['16-bit\ncurrent', '16-bit\nnearest', '24-bit\ncurrent', '16-bit\n80 dB floor*'], bars, color=['#d68910','#d68910','#2874a6','#148f77'])
    axes[1,1].set(title='C3 first-neighbour agreement with FLOAT', ylabel='Percent', ylim=(0,110))
    for i, value in enumerate(bars): axes[1,1].text(i, value+1, f'{value:.1f}%', ha='center', fontsize=9)
    fig.suptitle('PCM precision audit | *Floor change is a diagnostic, not a deployed fix', fontsize=13)
    fig.savefig(folder/'precision_audit.png', dpi=160)
    plt.close(fig)
    print(json.dumps({'c3_floor_diagnostic': result['c3_floor_only_change']['retrieval'], 'full_pool_gain': result['full_pool_matched_to_current_study_target'], 'worst_centroid': result['worst_full_centroid_case']}, indent=2))


if __name__ == '__main__':
    main()
