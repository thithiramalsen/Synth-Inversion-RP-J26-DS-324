"""Package only verified playback assets and the immutable bundle for Git hosting."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def pack(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Use a new destination; do not replace deployed study audio')
    bundle = json.loads(source.read_text(encoding='utf-8'))
    assets = [(s['playback_path'], s['playback_sha256']) for s in bundle['samples'].values()]
    assets += [('audio/'+s['path'], s['sha256']) for s in bundle['headphones']]
    assets += [('audio/'+bundle['calibration']['path'], bundle['calibration']['sha256'])]
    for relative, expected in assets:
        path = (source.parent / relative).resolve()
        if not path.is_relative_to(source.parent) or path.suffix.lower() != '.wav':
            raise ValueError('Unexpected playback asset path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Playback hash mismatch: {relative}')
    output.mkdir(parents=True)
    for relative, expected in assets:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source.parent / relative, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
    shutil.copyfile(source, output/'bundle.json')
    return dict(playback_assets=len(assets), bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),
                bundle_sha256=hashlib.sha256(source.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data/processed/c1_review_20_v1/bundle.json')
    parser.add_argument('--output', default='survey/deploy/study')
    args = parser.parse_args()
    print(json.dumps(pack(args.source, args.output), indent=2))
