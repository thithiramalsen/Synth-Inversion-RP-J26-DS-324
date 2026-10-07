"""Checks for the combined 13-control profile, without creating a study dataset."""

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import vita

from generation import bend_sustain_config as profile
from generation.compare_architectures import render_synth
from generation.vital_setup import DEFAULT_PROFILE, apply_parameters, create_synth, set_sample_rate, validate_synth

ROOT = profile.PROJECT_ROOT


@unittest.skipUnless(profile.BASE_PRESET.exists(), "Build the combined preset first")
class BendSustainTests(unittest.TestCase):
    def render(self, **values):
        synth = create_synth(profile)
        apply_parameters(synth, profile, dict(profile.BASE_VALUES, **values))
        return render_synth(synth)

    def test_schema_and_conditional_sustain_effect(self):
        self.assertEqual(DEFAULT_PROFILE, profile.DATASET_NAME)
        self.assertEqual(len(profile.PARAMS), 13)
        self.assertIn("bend_amount", profile.PARAMS)
        self.assertNotIn("env_2_sustain", profile.FIXED_CONTROLS)
        self.assertEqual(profile.FIXED_CONTROLS["osc_2_on"], ("raw", 0.))
        for bend in (.25, .5, .75):
            low = self.render(bend_amount=bend, filter_env_sustain=0.)
            high = self.render(bend_amount=bend, filter_env_sustain=1.)
            self.assertGreater(float(np.max(np.abs(low - high))), 1e-4)
            # Zero modulation depth must remove the effect of ENV2 sustain.
            np.testing.assert_array_equal(
                self.render(bend_amount=bend, filter_env_amount=.5, filter_env_sustain=0.),
                self.render(bend_amount=bend, filter_env_amount=.5, filter_env_sustain=1.))

    def test_combined_values_survive_repeat_and_preset_roundtrip(self):
        parent = (ROOT / "generation/test_renders").resolve()
        temporary = tempfile.TemporaryDirectory(prefix="combined-preset-test-", dir=parent)
        directory = Path(temporary.name).resolve()
        try:
            for bend, sustain in ((.25, .4), (.75, 1.)):
                values = dict(profile.BASE_VALUES, bend_amount=bend, filter_env_sustain=sustain)
                synth = create_synth(profile)
                apply_parameters(synth, profile, values)
                path = directory / "test.vital"
                path.write_text(synth.to_json(), encoding="utf-8")
                original = render_synth(synth)
                np.testing.assert_array_equal(original, self.render(**values))
                loaded = vita.Synth()
                set_sample_rate(loaded, profile.SAMPLE_RATE)
                self.assertTrue(loaded.load_preset(str(path)))
                validate_synth(loaded, profile)
                for name, expected in values.items():
                    actual = loaded.get_controls()[profile.PARAMS[name]["control"]].get_normalized()
                    self.assertAlmostEqual(actual, expected, delta=2e-6)
                np.testing.assert_array_equal(original, render_synth(loaded))
        finally:
            self.assertEqual(directory.parent, parent)
            self.assertTrue(directory.name.startswith("combined-preset-test-"))
            temporary.cleanup()

    def test_default_generator_uses_both_controls_in_isolated_two_sample_smoke_test(self):
        parent = (ROOT / "generation/test_renders").resolve()
        temporary = tempfile.TemporaryDirectory(prefix="combined-generator-test-", dir=parent)
        directory = Path(temporary.name).resolve()
        try:
            for relative in (
                "generation/params_config.py", "generation/restricted_config.py",
                "generation/bend_config.py", "generation/bend_sustain_config.py",
                "generation/vital_setup.py", "generation/scripts/05_generate_pilot_dataset.py",
                "generation/audio_processing.py", "generation/audio_policies/dc_highpass_10hz_v1.json",
                "generation/presets/base_restricted_bend_sustain_v4.vital",
            ):
                destination = directory / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            result = subprocess.run([sys.executable, "-B", "generation/scripts/05_generate_pilot_dataset.py", "--count", "2"],
                                    cwd=directory, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with (directory / "data/manifests/restricted_bend_sustain_v4.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            columns = {k for k in rows[0] if k.endswith("_normalized")}
            self.assertEqual(len(columns), 13)
            self.assertIn("bend_amount_normalized", columns)
            self.assertIn("filter_env_sustain_normalized", columns)
            config = json.loads((directory / "data/manifests/restricted_bend_sustain_v4_config.json").read_text())
            self.assertNotIn("env_2_sustain", config["fixed_controls"])
            self.assertEqual([p.name for p in (directory / "data/raw/audio").iterdir()], [profile.DATASET_NAME])
            self.assertEqual(config['audio_policy_id'], 'dc_highpass_10hz_v1')
            saved = {r['sample_id']:(r['audio_sha256'], r['raw_audio_sha256']) for r in rows}
            result = subprocess.run([sys.executable, '-B', 'generation/scripts/05_generate_pilot_dataset.py', '--count', '4', '--resume'],
                                    cwd=directory, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with (directory / 'data/manifests/restricted_bend_sustain_v4.csv').open(newline='', encoding='utf-8') as handle:
                extended = list(csv.DictReader(handle))
            self.assertEqual(len(extended), 4)
            self.assertEqual(saved, {r['sample_id']:(r['audio_sha256'], r['raw_audio_sha256']) for r in extended[:2]})
            # Resume must reject modified raw evidence even when processed files match.
            (directory / extended[0]['raw_audio_path']).write_bytes(b'tampered test fixture')
            result = subprocess.run([sys.executable, '-B', 'generation/scripts/05_generate_pilot_dataset.py', '--count', '4', '--resume'],
                                    cwd=directory, capture_output=True, text=True, timeout=120)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('raw', (result.stdout + result.stderr).lower())
        finally:
            self.assertEqual(directory.parent, parent)
            self.assertTrue(directory.name.startswith("combined-generator-test-"))
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
