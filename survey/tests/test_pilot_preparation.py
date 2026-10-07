"""Synthetic fixtures verify transformations and accounting, not perceptual validity."""
import csv
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from generation import bend_sustain_config as profile
from generation.audio_processing import DC_POLICY_ID, dc_filter
from survey.prepare_c1_pilot import prepare
from survey.analyze_c1_pilot import summarize
from c1_timbre.extract_pilot_features import extract_bundle


def test_production_preparation_preserves_sources_and_feature_signal(tmp_path):
    # Sixty-eight distinct synthetic candidates exercise the 64 + 3 selection.
    # No Vital renders, real participants or existing dataset files are used.
    source = tmp_path / 'source'
    source.mkdir()
    time = np.arange(132300) / 44100
    envelope = np.maximum(0, 1-time/2.5) * np.minimum(time/.02, 1)
    rng = np.random.default_rng(927)
    rows = []
    for i in range(68):
        raw = source / f'raw_{i}.wav'
        processed = source / f'processed_{i}.wav'
        signal = .04 * np.sin(2*np.pi*(150+17*i)*time) * envelope
        sf.write(raw, signal, 44100, subtype='FLOAT')
        stored_raw, _ = sf.read(raw)
        sf.write(processed, dc_filter(stored_raw, 44100), 44100, subtype='FLOAT')
        rows.append(dict(sample_id=f'fixture_{i}', audio_path=str(processed),
            audio_sha256=hashlib.sha256(processed.read_bytes()).hexdigest(),
            raw_audio_path=str(raw), raw_audio_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
            audio_policy_id=DC_POLICY_ID,
            **{k+'_normalized':v['min']+rng.random()*(v['max']-v['min']) for k,v in profile.PARAMS.items()}))
    manifest = tmp_path / 'candidates.csv'
    with manifest.open('w', newline='') as handle:
        writer=csv.DictWriter(handle, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    manifest.with_name('candidates_config.json').write_text(json.dumps(dict(
        dataset_name=profile.DATASET_NAME, audio_policy_id=DC_POLICY_ID, parameters=profile.PARAMS)))
    # ROOT is changed only for source-path serialization; policy/design hashes use repo code.
    repo_root = Path(__file__).resolve().parents[2]
    (tmp_path/'survey').mkdir()
    (tmp_path/'survey/design.py').write_bytes((repo_root/'survey/design.py').read_bytes())
    with patch('survey.prepare_c1_pilot.ROOT', tmp_path):
        bundle_path=prepare(manifest, tmp_path/'bundle')
        with pytest.raises(FileExistsError):
            prepare(manifest, tmp_path/'bundle')
    bundle=json.loads(bundle_path.read_text())
    assert len(bundle['samples'])==67
    assert len(bundle['assignments'])==16
    assert all(len(a['trials'])==39 for a in bundle['assignments'])
    assert bundle['selection']['excluded']==[]
    for sample in bundle['samples'].values():
        audio,_=sf.read(bundle_path.parent/sample['feature_path'])
        playback,_=sf.read(bundle_path.parent/sample['playback_path'])
        original=tmp_path/sample['source_path']
        before,_=sf.read(original)
        np.testing.assert_allclose(audio, before*sample['gain'], atol=3e-8, rtol=1e-7)
        assert np.max(np.abs(audio-playback)) <= 1/32768 + 1e-7
        assert np.max(np.abs(audio)) <= .890001
        assert hashlib.sha256(original.read_bytes()).hexdigest()==sample['source_sha256']
    # The headphone test must retain a quiet interval, an ordinary interval and
    # an antiphase interval; changing to mono or matching their RMS breaks it.
    correct=[]
    for screen in bundle['headphones']:
        wave,rate=sf.read(bundle_path.parent/'audio'/screen['path'])
        segments=[wave[round(t*rate):round((t+1)*rate)] for t in (0,1.5,3)]
        rms=[np.sqrt(np.mean(s*s)) for s in segments]
        assert np.argmin(rms)+1==screen['correct_interval']
        assert sum(np.mean(s[:,0]*s[:,1])<0 for s in segments)==1
        assert abs(20*np.log10(min(rms)/max(rms))+6)<.02
        correct.append(screen['correct_interval'])
    assert sorted(correct)==[1,1,2,2,3,3]
    features=tmp_path/'features.csv'
    assert extract_bundle(bundle_path, features)==64
    with features.open(newline='') as handle:
        feature_rows=list(csv.DictReader(handle))
    assert len({r['sample_id'] for r in feature_rows})==64
    first=next(iter(bundle['samples'].values()))
    (bundle_path.parent/first['feature_path']).write_bytes(b'changed fixture')
    with pytest.raises(ValueError, match='hash mismatch'):
        extract_bundle(bundle_path, tmp_path/'tampered.csv')


def test_analysis_excludes_repeats_from_independent_counts():
    base=dict(analysis_include='True', bundle_hash='bundle', protocol_hash='protocol',
              session_id='session',participant_id='person',sample_id='sound',
              presentation_id='primary',kind='primary',repeat_of='',
              brightness='4',roughness='unclear',percussiveness='2')
    repeat=dict(base,presentation_id='repeat',kind='repeat',repeat_of='primary',brightness='6')
    ignored=dict(base,analysis_include='False',session_id='rehearsal')
    result=summarize([base,repeat,ignored])
    assert result['independent_evaluations']==1
    assert result['listeners_per_sound']=={'sound':1}
    assert result['traits']['brightness']['repeat_median_absolute_difference']==2
    assert result['traits']['roughness']['unclear']==1
    assert result['traits']['roughness']['repeat_pairs']==0
    with pytest.raises(ValueError, match='more than one primary'):
        summarize([base,dict(base,presentation_id='duplicate')])
    with pytest.raises(ValueError, match='Mixed audio/protocol'):
        summarize([base,dict(repeat,protocol_hash='different')])
    with pytest.raises(ValueError, match='Repeat does not match'):
        summarize([base,dict(repeat,sample_id='different')])
