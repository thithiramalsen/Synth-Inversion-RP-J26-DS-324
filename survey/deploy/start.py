"""Production host entry point. Refuses ephemeral storage or changed study audio."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def validate_assets(bundle_path):
    bundle_path = Path(bundle_path).resolve()
    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    assets = [(s['playback_path'], s['playback_sha256']) for s in bundle['samples'].values()]
    assets += [('audio/'+s['path'], s['sha256']) for s in bundle['headphones']]
    assets += [('audio/'+bundle['calibration']['path'], bundle['calibration']['sha256'])]
    for relative, expected in assets:
        path = (bundle_path.parent / relative).resolve()
        if not path.is_relative_to(bundle_path.parent) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'Study playback asset failed verification: {relative}')
    return bundle


def main():
    if not os.environ.get('SURVEY_DATABASE_URL'):
        raise RuntimeError('Set the persistent PostgreSQL connection in SURVEY_DATABASE_URL')
    if len(os.environ.get('SURVEY_ADMIN_TOKEN', '')) < 32:
        raise RuntimeError('Set a random SURVEY_ADMIN_TOKEN of at least 32 characters')
    if not os.environ.get('SURVEY_RESEARCHER_USERNAME') or '$' not in os.environ.get('SURVEY_RESEARCHER_PASSWORD_HASH', ''):
        raise RuntimeError('Set the researcher username and password hash in host secrets')
    os.environ.setdefault('SURVEY_REMOTE_MODE', '1')
    os.environ.setdefault('SURVEY_C1_OPEN', '0')
    os.environ.setdefault('SURVEY_ALLOWED_ORIGINS', '')
    os.environ.setdefault('SURVEY_C1_BUNDLE', str(ROOT/'survey/deploy/study/bundle.json'))
    os.environ.setdefault('SURVEY_C1_CONFIG', str(ROOT/'survey/config/c1_review_20_v1.json'))
    validate_assets(os.environ['SURVEY_C1_BUNDLE'])
    validate_assets(ROOT/'survey/deploy/study/c4_bundle.json')
    sys.path.insert(0, str(ROOT/'survey/backend'))
    import uvicorn
    # Render's ingress supplies the public HTTPS scheme. This entry point runs
    # behind that proxy; local rehearsal continues to use run_rehearsal instead.
    uvicorn.run('main:app', host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
                proxy_headers=True, forwarded_allow_ips='*')


if __name__ == '__main__':
    main()
