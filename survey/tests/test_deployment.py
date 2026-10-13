"""Deployment must preserve playback bytes and exclude local/private files."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from survey.deploy.pack_study import pack
from survey.deploy.start import main, validate_assets

ROOT = Path(__file__).resolve().parents[2]


def fixture_bundle(tmp_path):
    source = tmp_path / 'source'
    (source / 'audio').mkdir(parents=True)
    digest = hashlib.sha256(b'fixture-audio').hexdigest()
    for name in ('sound.wav', 'headphone.wav', 'volume.wav'):
        (source / 'audio' / name).write_bytes(b'fixture-audio')
    (source / 'audio' / 'sound_features.wav').write_bytes(b'feature-master-not-for-host')
    (source / 'private_access.json').write_text('private-fixture')
    (source / 'responses.db').write_bytes(b'private-fixture')
    bundle = dict(samples={'s1': dict(playback_path='audio/sound.wav', playback_sha256=digest)},
                  headphones=[dict(path='headphone.wav', sha256=digest)],
                  calibration=dict(path='volume.wav', sha256=digest))
    path = source / 'bundle.json'
    path.write_text(json.dumps(bundle))
    return path, bundle


def test_package_copies_only_required_playback_and_preserves_bundle(tmp_path):
    source, bundle = fixture_bundle(tmp_path)
    output = tmp_path / 'deployment'
    result = pack(source, output)
    assert result['playback_assets'] == 3
    assert (output / 'bundle.json').read_bytes() == source.read_bytes()
    assert sorted(p.name for p in output.rglob('*') if p.is_file()) == [
        'bundle.json', 'headphone.wav', 'sound.wav', 'volume.wav']
    assert validate_assets(output / 'bundle.json') == bundle
    with pytest.raises(FileExistsError):
        pack(source, output)


def test_package_and_start_reject_changed_audio(tmp_path):
    source, _ = fixture_bundle(tmp_path)
    (source.parent / 'audio/sound.wav').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        pack(source, tmp_path / 'deployment')
    assert not (tmp_path / 'deployment').exists()
    with pytest.raises(RuntimeError, match='verification'):
        validate_assets(source)


def test_package_rejects_assets_outside_study_directory(tmp_path):
    source, bundle = fixture_bundle(tmp_path)
    (tmp_path / 'outside.wav').write_bytes(b'fixture-audio')
    bundle['samples']['s1']['playback_path'] = '../outside.wav'
    source.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match='path'):
        pack(source, tmp_path / 'deployment')
    with pytest.raises(RuntimeError, match='verification'):
        validate_assets(source)


def test_host_entrypoint_refuses_ephemeral_storage_and_missing_credentials():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match='persistent PostgreSQL'):
            main()
        os.environ['SURVEY_DATABASE_URL'] = 'postgresql://fixture.invalid/test'
        with pytest.raises(RuntimeError, match='SURVEY_ADMIN_TOKEN'):
            main()
        os.environ['SURVEY_ADMIN_TOKEN'] = 'test-only-secret-at-least-32-characters'
        with pytest.raises(RuntimeError, match='password hash'):
            main()


def test_committed_review_package_has_original_hashes_and_twenty_unique_sounds():
    path = ROOT / 'survey/deploy/study/bundle.json'
    bundle = validate_assets(path)
    assert bundle['rehearsal'] is True
    assert bundle['study_id'] == 'c1_20_review_v1'
    assert len(bundle['samples']) == 67
    assert len(list((path.parent / 'audio').glob('*.wav'))) == 74
    for block in bundle['assignments']:
        assert len(block['trials']) == 23
        primary = [trial['sample_id'] for trial in block['trials'] if trial['kind'] == 'primary']
        assert len(set(primary)) == len(primary) == 20
        assert sum(trial['kind'] == 'practice' for trial in block['trials']) == 3
