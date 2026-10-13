"""Fast synthetic tests; no corpus/test-set reads and no Vital rendering."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from argparse import Namespace

import numpy as np
import pandas as pd
import torch

from c2_estimation.pipeline import ParameterCNN, create_mel_filterbank, extract_log_mel
from c2_estimation.v4.baseline import CachedDataset, regression_metrics, train, atomic_checkpoint
from c2_estimation.v4.data import (NAMES, COUNTS, assignments, from_z, inverse_rows,
                                  load_prepared, sha, to_z, validate_frame, write_json)
from c2_estimation.v4.diagnostics import distance, perturbation_pair
from c2_estimation.v4.features import training_statistics


class ProtocolTests(unittest.TestCase):
    def test_fixed_complete_disjoint_and_development_exclusion(self):
        first = assignments(131072)
        pd.testing.assert_frame_equal(first, assignments(131072))
        self.assertEqual(first.split.value_counts().to_dict(), COUNTS)
        self.assertTrue((first.iloc[:1024].split == "train").all())
        self.assertEqual(first.validation_role.value_counts()["inverse"], 4096)
        self.assertEqual(first.validation_role.value_counts()["reliability"], 4096)
        diagnostic = first[first.diagnostic_rank >= 0]
        self.assertEqual(diagnostic.split.value_counts().to_dict(),
                         {"train": 128, "calibration": 2048, "validation": 512, "test": 1024})
        self.assertTrue((diagnostic[diagnostic.split == "validation"].validation_role == "reliability").all())
        self.assertFalse(first.equals(assignments(131072, seed=1)))

    def test_inverse_selection_never_touches_test_or_reliability(self):
        frame = assignments(131072)
        frame["sample_index"] = np.arange(len(frame))
        small = inverse_rows(frame, "development")
        self.assertEqual(small.split.value_counts().to_dict(), {"train": 4096, "validation": 512})
        self.assertTrue((small[small.split == "validation"].validation_role == "inverse").all())
        full = inverse_rows(frame, "full")
        self.assertEqual(full.split.value_counts().to_dict(), {"train": 98304, "validation": 4096})

    def test_tampered_manifest_is_rejected(self):
        # Some Windows sandboxes expose an unwritable inherited system TEMP.
        scratch_root = Path(__file__).resolve().parents[2] / "data/processed"
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="c2-test-", dir=scratch_root) as folder:
            root = Path(folder)
            (root / "manifest.parquet").write_bytes(b"original")
            (root / "split_manifest.csv").write_text("frozen", encoding="utf-8")
            write_json(root / "protocol.json", {"manifest_sha256": sha(root / "manifest.parquet"),
                                                "split_sha256": sha(root / "split_manifest.csv")})
            (root / "manifest.parquet").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                load_prepared(root)

    def test_readbacks_not_sobol_coordinates_and_duplicate_detection(self):
        recipe = {"synthesis": {"parameter_order": list(NAMES),
                  "parameters": {n: {"min": 0., "max": 1.} for n in NAMES}}}
        frame = pd.DataFrame({"sample_id": ["a", "b"], "sample_index": [0, 1],
            "raw_audio_path": ["a.wav", "b.wav"], "audio_policy_id": ["dc_highpass_10hz_v1"]*2,
            "raw_samples_sha256": ["r"]*2, "processed_samples_sha256": ["p"]*2,
            **{n + "_normalized": [.2, .8] for n in NAMES}})
        report = validate_frame(frame, recipe, expected_count=2)
        self.assertEqual(report["parameter_count"], 13)
        frame.loc[1, [n + "_normalized" for n in NAMES]] = .2
        with self.assertRaisesRegex(ValueError, "Duplicate complete"):
            validate_frame(frame, recipe, expected_count=2)


class CoordinateTests(unittest.TestCase):
    def test_narrow_range_roundtrip_and_step(self):
        lower, upper = np.array([.5]), np.array([.5625])
        np.testing.assert_allclose(to_z(np.array([.53125]), lower, upper), [.5])
        self.assertAlmostEqual(float(from_z(np.array([.52]), lower, upper)[0]-.53125), .00125)
        np.testing.assert_allclose(from_z(to_z(np.array([.521]), lower, upper), lower, upper), [.521])

    def test_invalid_values_fail_without_silent_clipping(self):
        for value in (np.nan, np.inf, -1., 2.):
            with self.assertRaises(ValueError):
                to_z(np.array([value]), np.array([0.]), np.array([1.]))
            with self.assertRaises(ValueError):
                from_z(np.array([value]), np.array([0.]), np.array([1.]))


class FeatureAndModelTests(unittest.TestCase):
    def test_normalization_fits_training_only(self):
        array = np.full((3, 64, 259), 999., dtype=np.float32)
        array[0] = -60.
        array[1] = -20.
        mean, std = training_statistics([array], np.array([0, 1]))
        self.assertAlmostEqual(mean, -40.)
        self.assertAlmostEqual(std, 20.)

    def test_logmel_shape_finite_and_fixed_floor(self):
        audio = np.zeros(132300, dtype=np.float32)
        bank = create_mel_filterbank(44100, 2048, 64, 20., 20000.)
        feature = extract_log_mel(audio, np.hanning(2048).astype(np.float32), bank, 2048, 512, 80.)
        self.assertEqual(feature.shape, (64, 259))
        self.assertTrue(np.isfinite(feature).all())
        np.testing.assert_array_equal(feature, -80.)

    def test_dataset_does_not_mutate_memmap_or_targets(self):
        arrays = [np.zeros((1, 64, 259), dtype=np.float32)]
        targets = np.zeros((1, 13), dtype=np.float32)
        targets.setflags(write=False)
        data = CachedDataset(arrays, targets, np.array([0]), -40., 20.)
        x, y = data[0]
        x.fill_(7.)
        y.fill_(7.)
        self.assertFalse(arrays[0].any())
        self.assertFalse(targets.any())

    def test_model_has_13_bounded_outputs_and_gradients(self):
        torch.set_num_threads(2)
        model = ParameterCNN(np.zeros(13, dtype=np.float32), np.ones(13, dtype=np.float32))
        result = model(torch.zeros(2, 1, 64, 259))
        self.assertEqual(tuple(result.shape), (2, 13))
        self.assertTrue(torch.all((result >= 0) & (result <= 1)))
        result.mean().backward()
        self.assertTrue(all(p.grad is not None for p in model.parameters()))

    def test_metrics_two_coordinates_and_constant_target(self):
        truth = np.tile(np.linspace(.1, .9, 3)[:, None], (1, 13))
        metrics = regression_metrics(truth, truth, np.zeros(13), np.ones(13))
        self.assertEqual(len(metrics), 26)
        self.assertTrue(all(r["mae"] == 0 and r["r_squared"] == 1 for r in metrics))
        constant = regression_metrics(truth, np.zeros_like(truth), np.zeros(13), np.ones(13))
        self.assertTrue(all(r["r_squared"] is None for r in constant))


class DiagnosticTests(unittest.TestCase):
    def test_distance_identity_symmetry_and_gain_sensitivity(self):
        time = np.arange(132300) / 44100
        first = .1*np.sin(2*np.pi*440*time)
        second = .05*np.sin(2*np.pi*660*time)
        self.assertEqual(distance(first, first), 0.)
        self.assertAlmostEqual(distance(first, second), distance(second, first), places=12)
        self.assertGreater(distance(first, .5*first), 0.)
        self.assertEqual(distance(np.zeros_like(first), np.zeros_like(first)), 0.)

    def test_silent_tail_floor_suppresses_numerical_noise(self):
        zero = np.zeros(132300)
        # The log term should not amplify subnormal tail changes; SC is separately finite.
        self.assertTrue(np.isfinite(distance(zero, np.full_like(zero, 1e-40))))
        self.assertLess(distance(zero, np.full_like(zero, 1e-40)), 1e-20)

    def test_central_and_boundary_isolation_preserve_input(self):
        for value, mode, expected_step in ((.5, "central", .04), (0., "forward", .02),
                                           (1., "backward", .02), (.01, "forward", .02)):
            z = np.full(13, .5)
            z[2] = value
            original = z.copy()
            minus, plus, observed = perturbation_pair(z, 2)
            self.assertEqual(observed, mode)
            self.assertAlmostEqual(plus[2]-minus[2], expected_step)
            np.testing.assert_array_equal(z, original)
            other = np.arange(13) != 2
            np.testing.assert_array_equal(minus[other], z[other])
            np.testing.assert_array_equal(plus[other], z[other])
            self.assertTrue(np.all(minus >= 0) and np.all(plus <= 1))


class ResumeTests(unittest.TestCase):
    def test_interrupted_epoch_resume_matches_uninterrupted_training(self):
        scratch_root = Path(__file__).resolve().parents[2] / "data/processed"
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="c2-resume-test-", dir=scratch_root) as folder:
            root = Path(folder)
            prepared = root / "prepared"
            prepared.mkdir()
            write_json(prepared / "protocol.json", {"fixture": True})
            protocol = {"lower": [0.]*13, "upper": [1.]*13}
            rng = np.random.default_rng(123)
            features = [rng.normal(-40, 10, (12, 64, 259)).astype(np.float32)]
            frame = pd.DataFrame({"sample_id": [f"fixture_{i}" for i in range(12)],
                "sample_index": np.arange(12), "split": ["train"]*8 + ["validation"]*4,
                "validation_role": [""]*8 + ["inverse"]*4,
                **{n + "_z": rng.uniform(0, 1, 12) for n in NAMES}})
            cache = {"protocol_sha256": sha(prepared / "protocol.json"),
                     "signature": "synthetic-test-only", "scope": "development"}
            args = Namespace(prepared=prepared, cache=root / "unused", output=root / "whole",
                epochs=2, batch_size=4, patience=2, threads=1, seed=7, device="cpu",
                learning_rate=.001, weight_decay=.0001, resume=False)
            with patch("c2_estimation.v4.baseline.load_prepared", return_value=(protocol, frame)), \
                 patch("c2_estimation.v4.baseline.load_cache", return_value=(cache, frame, features)), \
                 patch("c2_estimation.v4.baseline.save_examples"):
                train(args)
                expected = torch.load(args.output / "last_model.pt", weights_only=True)
                expected_predictions = (args.output / "validation_predictions.csv").read_bytes()
                args.output = root / "interrupted"

                def interrupt_after_checkpoint(path, state):
                    atomic_checkpoint(path, state)
                    if path.name == "last_model.pt":
                        raise InterruptedError("simulated lost connection after epoch checkpoint")

                with patch("c2_estimation.v4.baseline.atomic_checkpoint", side_effect=interrupt_after_checkpoint):
                    with self.assertRaises(InterruptedError):
                        train(args)
                args.resume = True
                train(args)
                actual = torch.load(args.output / "last_model.pt", weights_only=True)
                self.assertEqual(expected["history"], actual["history"])
                for key in expected["model"]:
                    self.assertTrue(torch.equal(expected["model"][key], actual["model"][key]), key)
                self.assertEqual(expected_predictions, (args.output / "validation_predictions.csv").read_bytes())


if __name__ == "__main__":
    unittest.main()
