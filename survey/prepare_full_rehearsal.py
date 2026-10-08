"""Copy the frozen full C1 bundle into an isolated, explicitly labelled rehearsal.

No synth rendering, reselection, audio processing or production responses occur.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source: Path, output: Path):
    source = source.resolve()
    output = output.resolve()
    bundle = json.loads(source.read_text(encoding="utf-8"))
    if bundle["rehearsal"] or bundle["study_id"] != "c1_pilot_v1":
        raise ValueError("Expected the frozen production C1 pilot bundle")
    if output.exists():
        raise FileExistsError("Use a new rehearsal directory; never overwrite a study")
    if output == source.parent or source.parent.is_relative_to(output):
        raise ValueError("Rehearsal directory must not contain the production bundle")
    assert len(bundle['samples']) == 67 and len(bundle['assignments']) == 16
    assert all(len(a['trials']) == 39 for a in bundle['assignments'])
    paths = []
    for sample in bundle['samples'].values():
        paths.extend([(sample['playback_path'], sample['playback_sha256']),
                      (sample['feature_path'], sample['feature_sha256'])])
    paths += [('audio/'+item['path'], None) for item in bundle['headphones']]
    paths.append(('audio/'+bundle['calibration']['path'], None))
    checked = []
    for relative, expected in paths:
        path = (source.parent / relative).resolve()
        if not path.is_relative_to(source.parent):
            raise ValueError("Unexpected asset outside source bundle")
        actual = digest(path)
        if expected and actual != expected:
            raise ValueError(f"Changed source: {relative}")
        checked.append((relative, actual))
    original_hash = digest(source)
    output.mkdir(parents=True)
    for relative, expected in checked:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source.parent / relative, target)
        assert digest(target) == expected
    bundle.update(study_id="c1_full_rehearsal_v1", rehearsal=True,
                  rehearsal_source_bundle_sha256=original_hash,
                  rehearsal_note="Full 39-presentation researcher/usability rehearsal; excluded from research analysis.")
    destination = output / 'bundle.json'
    destination.write_text(json.dumps(bundle, indent=2)+'\n', encoding='utf-8')
    assert digest(source) == original_hash
    (output/'PREPARATION.json').write_text(json.dumps({
        'source_bundle_sha256': original_hash, 'rehearsal_bundle_sha256': digest(destination),
        'copied_assets': len(checked), 'audio_unchanged': True,
        'assignments': 16, 'presentations_per_assignment': 39,
        'source_bundle_unchanged': True,
        'implementation_sha256': digest(Path(__file__)),
    }, indent=2)+'\n', encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/processed/c1_pilot_v1/bundle.json')
    parser.add_argument('--output', type=Path, default=ROOT/'data/processed/c1_full_rehearsal_v1')
    args = parser.parse_args()
    print(prepare(args.source, args.output))
