"""Check that the selected profile implements the auditioned B architecture."""

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

from generation import bend_config as profile
from generation.compare_architectures import parameters, render_synth
from generation.vital_setup import apply_parameters, create_synth, validate_synth

ROOT = profile.PROJECT_ROOT


@unittest.skipUnless(profile.BASE_PRESET.exists(), "Build the Bend preset first")
class BendConfigurationTests(unittest.TestCase):
    def test_selected_schema_and_fixed_architecture(self):
        self.assertEqual(len(profile.PARAMS), 12)
        self.assertEqual(list(profile.PARAMS)[:2], ["wave_frame", "bend_amount"])
        self.assertNotIn("filter_env_sustain", profile.PARAMS)
        synth = create_synth(profile)
        controls = synth.get_controls()
        self.assertEqual(synth.get_control_text("osc_1_distortion_type"), "Bend")
        self.assertEqual(controls["env_2_sustain"].value(), 0)
        self.assertEqual(controls["osc_2_on"].value(), 0)

    def test_wrong_mode_or_variable_filter_sustain_rejected(self):
        for name, wrong in (("osc_1_distortion_type", 0.), ("env_2_sustain", .4)):
            synth = create_synth(profile)
            synth.get_controls()[name].set(wrong)
            with self.assertRaisesRegex(ValueError, "Fixed control mismatch"):
                validate_synth(synth, profile)

    def test_profile_matches_saved_B_audio(self):
        raw = ROOT / "generation/test_renders/architecture_ab_v1/raw"
        if not raw.exists():
            self.skipTest("Local comparison audio unavailable")
        for background in ("clean_held", "driven_pluck"):
            for bend in (.25, .5, .75):
                values = parameters(background, .5, .575, 0.)
                values.pop("filter_env_sustain")
                values["bend_amount"] = bend
                synth = create_synth(profile)
                apply_parameters(synth, profile, values)
                actual = render_synth(synth)
                b = f"{bend:.3f}".replace(".", "p")
                saved, rate = sf.read(raw / f"B_{background}_w0p500_c0p575_s0p000_b{b}.wav", dtype="float32")
                self.assertEqual(rate, profile.SAMPLE_RATE)
                np.testing.assert_array_equal(actual, saved)

    def test_explicit_B_profile_keeps_separate_schema_and_resumes(self):
        parent = (ROOT / "generation/test_renders").resolve()
        temporary = tempfile.TemporaryDirectory(prefix="bend-profile-test-", dir=parent)
        root = type(ROOT)(temporary.name).resolve()
        try:
            for relative in (
                "generation/params_config.py", "generation/restricted_config.py", "generation/bend_config.py", "generation/bend_sustain_config.py",
                "generation/vital_setup.py", "generation/scripts/05_generate_pilot_dataset.py",
                "generation/presets/base_restricted_bend_v3.vital",
            ):
                dst = root / relative
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, dst)
            command = [sys.executable, "-B", "generation/scripts/05_generate_pilot_dataset.py", "--profile", "restricted_bend_v3"]
            first = subprocess.run(command + ["--count", "2"], cwd=root, capture_output=True, text=True, timeout=120)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            directory = root / "data/raw/audio/restricted_bend_v3"
            hashes = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                      for p in directory.glob("*.wav")}
            resumed = subprocess.run(command + ["--count", "4", "--resume"], cwd=root,
                                     capture_output=True, text=True, timeout=120)
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            for name, expected in hashes.items():
                p = directory / name
                self.assertEqual((hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns), expected)
            with (root / "data/manifests/restricted_bend_v3.csv").open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4)
            self.assertIn("bend_amount_normalized", rows[0])
            self.assertNotIn("filter_env_sustain_normalized", rows[0])
            config = json.loads((root / "data/manifests/restricted_bend_v3_config.json").read_text())
            self.assertEqual(config["fixed_controls"]["env_2_sustain"]["value"], 0.)
            self.assertFalse((root / "data/raw/audio/restricted_v2").exists())
            self.assertFalse((root / "data/raw/audio/pilot_v1").exists())
        finally:
            self.assertEqual(root.parent, parent)
            self.assertTrue(root.name.startswith("bend-profile-test-"))
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
