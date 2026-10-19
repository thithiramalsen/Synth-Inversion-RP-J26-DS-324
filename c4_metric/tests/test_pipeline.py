from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from c4_metric.model import TripletProjection, cosine_distance, triplet_margin_loss
from c4_metric.c3_adapter import AdaptedScorer
from c4_metric.preference_data import normalize_responses
from c4_metric.similarity import score_similarity
from c4_metric.splits import create_splits
from c4_metric.synthetic_data.generate_dummy_c4 import simulate_responses
from c4_metric.synthetic_data.generate_synthetic_embeddings import generate
from c4_metric.train import train

ROOT = Path(__file__).resolve().parents[2]


class SimilarityTests(unittest.TestCase):
    def test_mfcc_stft_same_audio_and_length_difference(self):
        rate = 44_100
        t = np.arange(rate // 3) / rate
        tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        stereo = np.column_stack([tone, tone * .7])
        for method in ("mfcc", "stft", "ms_stft"):
            same = score_similarity((stereo, rate), (tone, rate), method)
            different = score_similarity((tone, rate),
                                         (np.sin(2 * np.pi * 1700 * np.arange(rate // 2) / rate), rate), method)
            self.assertAlmostEqual(same.similarity, 1.0, places=6)
            self.assertGreater(same.similarity, different.similarity)
            self.assertAlmostEqual(same.distance, 1.0 - same.similarity, places=6)

    def test_invalid_audio_and_method(self):
        with self.assertRaises(ValueError):
            score_similarity((np.zeros(256), 44_100), (np.ones(256), 44_100), "mfcc")
        with self.assertRaises(ValueError):
            score_similarity((np.ones(256), 44_100), (np.ones(256), 44_100), "unknown")

    def test_wav_loading_and_sample_rate_conversion(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "c4_metric/tests") as temp:
            rate = 22_050
            t = np.arange(rate // 2) / rate
            tone = np.sin(2 * np.pi * 620 * t).astype(np.float32)
            path = Path(temp) / "tone.wav"
            sf.write(path, tone, rate)
            resampled_match = score_similarity(path, (tone, rate), "stft")
            self.assertGreater(resampled_match.similarity, .99)


class TripletLossTests(unittest.TestCase):
    def test_margin_loss_exact_and_zero_cases(self):
        anchor = torch.tensor([[1.0, 0.0]])
        positive = torch.tensor([[1.0, 0.0]])
        negative = torch.tensor([[0.0, 1.0]])
        self.assertAlmostEqual(float(triplet_margin_loss(anchor, positive, negative, .2)), 0.0, places=6)
        violated = triplet_margin_loss(anchor, negative, positive, .2)
        self.assertAlmostEqual(float(violated), 1.2, places=6)

    def test_gradients_parameter_updates_and_shape_validation(self):
        torch.manual_seed(22)
        model = TripletProjection(8, 4)
        optimizer = torch.optim.SGD(model.parameters(), lr=.05)
        a = torch.randn(16, 8)
        p = torch.randn(16, 8)
        n = torch.randn(16, 8)
        before = model.projection.weight.detach().clone()
        loss = triplet_margin_loss(model(a), model(p), model(n), .5)
        loss.backward()
        self.assertTrue(torch.isfinite(model.projection.weight.grad).all())
        optimizer.step()
        self.assertFalse(torch.equal(before, model.projection.weight.detach()))
        with self.assertRaises(ValueError):
            triplet_margin_loss(a, p[:, :4], n, .2)


class SurveyProcessingTests(unittest.TestCase):
    def test_synthetic_assignment_gives_different_unique_question_sets(self):
        triplets = [{
            "triplet_id": f"Q{i:03d}",
            "reference_sample_id": f"R{i}",
            "candidate_a_sample_id": f"A{i}",
            "candidate_b_sample_id": f"B{i}",
        } for i in range(200)]
        responses, _ = simulate_responses(triplets, participants=50,
                                          questions_per_participant=20, seed=81)
        by_participant: dict[str, list[str]] = {}
        triplet_counts: dict[str, int] = {}
        for row in responses:
            by_participant.setdefault(str(row["participant_id"]), []).append(str(row["triplet_id"]))
            triplet_id = str(row["triplet_id"])
            triplet_counts[triplet_id] = triplet_counts.get(triplet_id, 0) + 1
        self.assertEqual(len(responses), 50 * 20)
        self.assertTrue(all(len(ids) == 20 and len(set(ids)) == 20
                            for ids in by_participant.values()))
        self.assertEqual(len({tuple(sorted(ids)) for ids in by_participant.values()}), 50)
        self.assertEqual(set(triplet_counts.values()), {5})

    def test_disagreement_uncertainty_duplicate_and_manifest_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "c4_metric/tests") as temp:
            root = Path(temp)
            manifest = root / "manifest.csv"
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sample_id"])
                writer.writeheader()
                writer.writerows({"sample_id": f"S{i}"} for i in range(4))
            responses = root / "responses.csv"
            fields = ["data_status", "participant_id", "triplet_id", "presentation_id",
                      "reference", "candidate_a", "candidate_b", "choice", "chosen_sample_id",
                      "confidence", "analysis_include"]
            rows = [
                ["SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE", "P1", "T1", "P1-T1", "S0", "S1", "S2", "candidate_a", "S1", "4", "false"],
                ["SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE", "P2", "T1", "P2-T1", "S0", "S2", "S1", "candidate_a", "S2", "2", "false"],
                ["SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE", "P3", "T1", "P3-T1", "S0", "S1", "S2", "cannot_decide", "", "", "false"],
                ["SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE", "P1", "T1", "P1-T1", "S0", "S1", "S2", "candidate_a", "S1", "4", "false"],
                ["SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE", "P4", "T2", "P4-T2", "UNKNOWN", "S1", "S2", "candidate_a", "S1", "3", "false"],
            ]
            with responses.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle); writer.writerow(fields); writer.writerows(rows)
            summary = normalize_responses(responses, manifest, root / "out", allow_synthetic=True)
            self.assertEqual(summary["valid_rows"], 3)
            self.assertEqual(summary["rejected_rows"], 2)
            with (root / "out/preference_triplets.csv").open(encoding="utf-8-sig") as handle:
                prefs = list(csv.DictReader(handle))
            self.assertEqual(len(prefs), 2)
            with (root / "out/aggregate_preferences.csv").open(encoding="utf-8-sig") as handle:
                aggregate = list(csv.DictReader(handle))
            self.assertEqual(aggregate[0]["majority_winner"], "tie")
            self.assertEqual(aggregate[0]["uncertain_count"], "1")

    def test_proposal_b_c_mapping(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "c4_metric/tests") as temp:
            root = Path(temp)
            manifest, responses, mapping = root / "manifest.csv", root / "responses.csv", root / "mapping.json"
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sample_id"])
                writer.writeheader(); writer.writerows({"sample_id": f"S{i}"} for i in range(3))
            with responses.open("w", newline="", encoding="utf-8") as handle:
                fields = ["participant_id", "comparison_id", "target_id", "candidate_b_id",
                          "candidate_c_id", "selected_candidate", "confidence", "analysis_include"]
                writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
                writer.writerow({"participant_id": "P1", "comparison_id": "T1", "target_id": "S0",
                                 "candidate_b_id": "S1", "candidate_c_id": "S2",
                                 "selected_candidate": "B", "confidence": "4", "analysis_include": "true"})
            mapping.write_text(json.dumps({
                "columns": {"participant_id": ["participant_id"], "comparison_id": ["comparison_id"],
                            "presentation_id": ["comparison_id"], "anchor_id": ["target_id"],
                            "candidate_a_id": ["candidate_b_id"], "candidate_b_id": ["candidate_c_id"],
                            "choice": ["selected_candidate"], "confidence": ["confidence"],
                            "analysis_include": ["analysis_include"]},
                "choice_values": {"B": "candidate_a", "C": "candidate_b"},
            }), encoding="utf-8")
            summary = normalize_responses(responses, manifest, root / "out", mapping_path=mapping)
            self.assertEqual(summary["preference_triplets"], 1)
            with (root / "out/preference_triplets.csv").open(encoding="utf-8-sig") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["positive_id"], "S1")
            self.assertEqual(row["negative_id"], "S2")


class SplitAndTrainingTests(unittest.TestCase):
    def test_identity_grouped_split_and_full_synthetic_training(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "c4_metric/tests") as temp:
            root = Path(temp)
            embeddings, triplets = generate(root / "dummy", triplets=90, dimension=32, seed=19)
            split_file, split_summary = root / "splits.csv", root / "splits.json"
            summary = create_splits(triplets, split_file, split_summary, seed=19)
            self.assertEqual(summary["cross_split_audio_overlap"], 0)
            trained = train(split_file, embeddings, root / "training", output_dim=16,
                            margin=.3, learning_rate=.01, batch_size=32, epochs=5,
                            patience=5, seed=19, allow_synthetic=True)
            self.assertTrue((root / "training/best_model.pt").is_file())
            self.assertTrue(trained["synthetic_evidence"])
            self.assertEqual(trained["test_rows_present_but_not_used"], summary["splits"]["test"]["records"])
            self.assertFalse(trained["test_labels_used_for_training_or_selection"])
            self.assertEqual(trained["training_split_name"], "train")
            self.assertEqual(trained["checkpoint_selection_split"], "validation")
            with self.assertRaisesRegex(ValueError, "synthetic-label checkpoint"):
                AdaptedScorer(root / "training/best_model.pt")


if __name__ == "__main__":
    unittest.main()
