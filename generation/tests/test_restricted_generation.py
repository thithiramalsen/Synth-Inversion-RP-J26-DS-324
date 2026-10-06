"""Real-render integration checks; run with the project's Vita environment."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from generation import restricted_config as profile
from generation.characterize import render
from generation.vital_setup import create_synth, load_profile, validate_synth

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(profile.BASE_PRESET.exists(), "Build restricted_v2 preset first")
class RoutingTests(unittest.TestCase):
    def test_legacy_eight_control_preset_still_validates(self):
        legacy = load_profile("pilot_v1")
        if not legacy.BASE_PRESET.exists():
            self.skipTest("Historical local preset is unavailable")
        create_synth(legacy)

    def test_missing_route_and_extra_oscillator_are_rejected(self):
        synth = create_synth(profile)
        synth.disconnect_modulation("env_2", "filter_1_cutoff")
        with self.assertRaisesRegex(ValueError, "routing mismatch"):
            validate_synth(synth, profile)
        synth = create_synth(profile)
        synth.get_controls()["osc_2_on"].set(1)
        with self.assertRaisesRegex(ValueError, "osc_2_on"):
            validate_synth(synth, profile)

    def test_filter_envelope_changes_audio_only_when_connected_with_depth(self):
        base = dict(profile.BASE_VALUES)
        low = render(dict(base, filter_env_attack=.05))
        high = render(dict(base, filter_env_attack=.35))
        self.assertGreater(float(np.max(np.abs(low - high))), 1e-4)
        zero = dict(base, filter_env_amount=.5)
        np.testing.assert_array_equal(render(dict(zero, filter_env_attack=.05)),
                                      render(dict(zero, filter_env_attack=.35)))
        np.testing.assert_array_equal(render(base), render(base))


@unittest.skipUnless(profile.BASE_PRESET.exists(), "Build restricted_v2 preset first")
class DatasetWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.parent = (ROOT / "generation/test_renders").resolve()
        self.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="generation-test-", dir=self.parent)
        self.root = Path(self.temporary.name).resolve()
        self.assertEqual(self.root.parent, self.parent)
        for relative in (
            "generation/params_config.py", "generation/restricted_config.py", "generation/bend_config.py", "generation/bend_sustain_config.py", "generation/vital_setup.py",
            "generation/scripts/05_generate_pilot_dataset.py", "generation/presets/base_restricted_v2.vital",
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        self.audio = self.root / "data/raw/audio/restricted_v2"
        self.csv = self.root / "data/manifests/restricted_v2.csv"

    def tearDown(self):
        # Only this test's newly created workspace can be removed recursively.
        self.assertEqual(self.root.resolve().parent, self.parent)
        self.assertTrue(self.root.name.startswith("generation-test-"))
        self.temporary.cleanup()

    def run_generator(self, *args, success=True):
        result = subprocess.run([sys.executable, "-B", "generation/scripts/05_generate_pilot_dataset.py", "--profile", "restricted_v2", *args],
                                cwd=self.root, capture_output=True, text=True, timeout=120)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def snapshot(self):
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in self.audio.glob("*.wav")}

    def test_extend_preserves_wavs_and_parameter_prefix(self):
        self.run_generator("--count", "4")
        first = self.snapshot()
        with self.csv.open(newline="", encoding="utf-8") as handle:
            before = list(csv.DictReader(handle))
        self.run_generator("--count", "8", "--resume")
        with self.csv.open(newline="", encoding="utf-8") as handle:
            after = list(csv.DictReader(handle))
        self.assertEqual(len(after), 8)
        self.assertEqual(after[:4], before)
        self.assertEqual({k: self.snapshot()[k] for k in first}, first)
        self.assertEqual(len([k for k in after[0] if k.endswith("_normalized")]), 12)
        saved = self.snapshot()
        self.run_generator("--count", "8", "--resume")
        self.assertEqual(saved, self.snapshot())
        for args in [("--count", "8"), ("--count", "4", "--resume"), ("--count", "7", "--resume")]:
            self.run_generator(*args, success=False)
            self.assertEqual(saved, self.snapshot())

    def test_resume_refuses_changed_config_audio_and_targets(self):
        self.run_generator("--count", "4")
        config = self.root / "data/manifests/restricted_v2_config.json"
        original = config.read_bytes()
        changed = json.loads(original)
        changed["parameters"]["filter_env_amount"]["max"] = .6
        config.write_text(json.dumps(changed), encoding="utf-8")
        self.assertIn("configuration changed", self.run_generator("--count", "8", "--resume", success=False).stderr)
        config.write_bytes(original)
        wav = next(self.audio.glob("*.wav"))
        audio = wav.read_bytes()
        wav.write_bytes(audio + b"changed")
        self.assertIn("modified saved WAV", self.run_generator("--count", "8", "--resume", success=False).stderr)
        wav.write_bytes(audio)
        with self.csv.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["filter_env_attack_normalized"] = "0.99"
        with self.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.assertIn("Saved parameter value changed", self.run_generator("--count", "8", "--resume", success=False).stderr)
        self.assertEqual(len(list(self.audio.glob("*.wav"))), 4)

    def test_invalid_preset_cannot_destroy_existing_dataset(self):
        self.run_generator("--count", "4")
        saved = self.snapshot()
        preset = self.root / "generation/presets/base_restricted_v2.vital"
        data = json.loads(preset.read_text(encoding="utf-8"))
        data["settings"]["modulations"][0] = {"source": "", "destination": ""}
        preset.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_generator("--count", "8", "--overwrite", success=False)
        self.assertIn("routing mismatch", result.stderr)
        self.assertEqual(saved, self.snapshot())


if __name__ == "__main__":
    unittest.main()
