from __future__ import annotations

import csv
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
import torch

from c4_metric.model import TripletProjection, cosine_distance, triplet_margin_loss
from c4_metric.c3_adapter import AdaptedScorer, MFCCAdaptedScorer, score_reference_against_candidates
from c4_metric.cache_mfcc_embeddings import extract as extract_mfcc_embeddings
from c4_metric.evaluate import evaluate
from c4_metric.analyze_confidence import analyze as analyze_confidence
from c4_metric.preference_data import normalize_responses
from c4_metric.similarity import score_similarity
from c4_metric.splits import create_splits
from c4_metric.synthetic_data.generate_dummy_c4 import simulate_responses
from c4_metric.synthetic_data.generate_synthetic_embeddings import generate
from c4_metric.train import load_arrays, train

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
    def test_vote_ties_unresolved_and_confidence_are_separate(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "c4_metric/tests") as temp:
            root = Path(temp)
            manifest, responses = root / "manifest.csv", root / "responses.csv"
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sample_id"])
                writer.writeheader()
                writer.writerows({"sample_id": f"S{i}"} for i in range(12))
            fields = ["participant_id", "comparison_id", "presentation_id", "anchor_id",
                      "candidate_a_id", "candidate_b_id", "choice", "confidence"]
            response_rows = []

            def add_group(anchor, candidates, choices):
                for i, (choice, confidence) in enumerate(choices):
                    response_rows.append({
                        "participant_id": f"P{i}_{anchor}", "comparison_id": anchor,
                        "presentation_id": f"{anchor}_{i}", "anchor_id": anchor,
                        "candidate_a_id": candidates[0], "candidate_b_id": candidates[1],
                        "choice": choice, "confidence": confidence,
                    })

            add_group("S0", ("S1", "S2"), [("candidate_a", "1"), ("candidate_a", "2"), ("candidate_b", "3")])
            add_group("S3", ("S4", "S5"), [("candidate_a", "4"), ("candidate_b", "5"), ("candidate_b", "")])
            add_group("S6", ("S7", "S8"), [("candidate_a", "5"), ("candidate_b", "1")])
            add_group("S9", ("S10", "S11"), [("cannot_decide", ""), ("cannot_decide", "bad")])
            with responses.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(response_rows)

            out = root / "out"
            summary = normalize_responses(responses, manifest, out)
            self.assertEqual(summary["majority_winner_counts"], {"first": 1, "second": 1})
            self.assertEqual(summary["vote_status_counts"], {"preference": 2, "tie": 1, "unresolved": 1})
            self.assertEqual(summary["tied_preference_rows_excluded"], 2)
            self.assertEqual(summary["trainable_preference_rows"], 6)
            self.assertEqual(summary["confidence_counts"], {"valid": 7, "missing": 2, "invalid": 1})
            with (out / "aggregate_preferences.csv").open(encoding="utf-8-sig") as handle:
                aggregates = {row["anchor_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual((aggregates["S6"]["votes_first"], aggregates["S6"]["votes_second"]), ("1", "1"))
            self.assertEqual(aggregates["S6"]["vote_status"], "tie")
            self.assertEqual(aggregates["S9"]["vote_status"], "unresolved")
            with (out / "preference_triplets.csv").open(encoding="utf-8-sig") as handle:
                preferences = list(csv.DictReader(handle))
            self.assertEqual(sum(row["vote_status"] == "tie" for row in preferences), 2)
            self.assertEqual(sum(row["vote_status"] == "unresolved" for row in preferences), 0)
            with (out / "aggregate_preference_triplets.csv").open(encoding="utf-8-sig") as handle:
                aggregate_triplets = list(csv.DictReader(handle))
            self.assertEqual(len(aggregate_triplets), 2)
            self.assertTrue(all(row["vote_status"] == "preference" for row in aggregate_triplets))
            report = analyze_confidence(out / "cleaned_responses.csv", out / "confidence.json")
            self.assertEqual(report["confidence_level_counts"]["5"]["count"], 2)
            self.assertEqual(report["confidence_level_counts"]["5"]["comparison_vote_status"]["tie"], 1)
            self.assertEqual(report["confidence_missing_count"], 2)
            self.assertEqual(report["confidence_invalid_count"], 1)

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
    def test_post_survey_mfcc26_cache_loads_in_c4_and_c3_audio_adapter(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "c4_metric/tests") as temp:
            root = Path(temp)
            manifest_path = root / "manifest.csv"
            triplets_path = root / "aggregate_preference_triplets.csv"
            audio_paths = []
            for index in range(27):
                rate = 44_100
                t = np.arange(rate // 4, dtype=np.float64) / rate
                tone = (0.15 * np.sin(2 * np.pi * (220 + index * 37) * t)).astype(np.float32)
                audio_path = root / f"sample_{index}.wav"
                sf.write(audio_path, tone, rate)
                audio_paths.append(audio_path)
            with manifest_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sample_id", "audio_path", "cutoff_normalized"])
                writer.writeheader()
                writer.writerows({"sample_id": f"S{i}", "audio_path": str(path),
                                  "cutoff_normalized": str(i / 10)} for i, path in enumerate(audio_paths))
            triplet_rows = [{"data_status": "human_response", "comparison_ids": f"Q{i}",
                             "anchor_id": f"S{i * 3}", "positive_id": f"S{i * 3 + 1}",
                             "negative_id": f"S{i * 3 + 2}", "vote_status": "preference"}
                            for i in range(9)]
            with triplets_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(triplet_rows[0]))
                writer.writeheader(); writer.writerows(triplet_rows)

            embedding_path = root / "mfcc26_embeddings.npz"
            metadata = extract_mfcc_embeddings(triplets_path, manifest_path, embedding_path)
            self.assertEqual(metadata["representation"], "mfcc26")
            self.assertEqual(metadata["feature_dimension"], 26)
            with np.load(embedding_path, allow_pickle=False) as archive:
                ids = archive["sample_ids"].astype(str).tolist()
                vectors = archive["embeddings"]
            self.assertEqual(vectors.shape, (27, 26))
            self.assertEqual(vectors.dtype, np.float32)
            self.assertEqual(len(metadata["samples"]), 27)
            self.assertEqual(metadata["samples"][0]["synthesizer_parameters"]["cutoff_normalized"], 0.0)
            # Load the unchanged C3 feature function without requiring its optional
            # plotting dependency; compare cache values against that real function.
            matplotlib_stub = types.ModuleType("matplotlib")
            matplotlib_stub.use = lambda *_args, **_kwargs: None
            pyplot_stub = types.ModuleType("matplotlib.pyplot")
            with patch.dict(sys.modules, {"matplotlib": matplotlib_stub,
                                          "matplotlib.pyplot": pyplot_stub}):
                c3_pipeline = importlib.import_module("c3_recommendation.pipeline")
                c3_settings = c3_pipeline.feature_settings({"sample_rate": 44_100})
                c3_vector = c3_pipeline.extract_mfcc_summary(
                    c3_pipeline.read_target_audio(audio_paths[0], 44_100), c3_settings)
            np.testing.assert_allclose(vectors[0], c3_vector.astype(np.float32), rtol=1e-6, atol=1e-6)

            split_path = root / "split_manifest.csv"
            split_summary = create_splits(triplets_path, split_path, root / "split_summary.json", seed=17)
            self.assertEqual(split_summary["eligible_rows"], 9)
            embeddings, indexes, _, _ = load_arrays(split_path, embedding_path, allow_synthetic=False)
            self.assertEqual(embeddings.shape, (27, 26))
            self.assertEqual(set(indexes), {"train", "validation", "test"})

            training = train(split_path, embedding_path, root / "training", output_dim=8,
                             batch_size=2, epochs=2, patience=2, seed=17)
            checkpoint_path = Path(training["checkpoint"])
            scorer = MFCCAdaptedScorer(checkpoint_path, device="cpu")
            vector_index = ids.index("S0")
            np.testing.assert_allclose(scorer.embed_audio(audio_paths[0]), vectors[vector_index],
                                       rtol=1e-5, atol=1e-5)
            score = scorer.score(audio_paths[0], audio_paths[1])
            self.assertEqual(score.method, "c4_mfcc26")
            self.assertTrue(np.isfinite(score.similarity))
            ranked = score_reference_against_candidates(audio_paths[0], [audio_paths[1]],
                                                        method="c4", scorer=scorer)
            self.assertEqual(len(ranked), 1)
            evaluation = evaluate(split_path, manifest_path, root / "evaluation",
                                  checkpoint=checkpoint_path, methods=("mfcc", "c4"),
                                  bootstrap_draws=100, seed=17, embedding_path=embedding_path)
            self.assertEqual(evaluation["embedding_cache"], "validated mfcc26 cache: 27 embeddings")
            self.assertEqual(evaluation["test_metrics"]["c4"]["aggregate_comparisons"], 1)

    def test_splits_exclude_ambiguous_rows_and_ignore_confidence_for_selection(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "c4_metric/tests") as temp:
            root = Path(temp)
            _, triplets = generate(root / "dummy", triplets=90, dimension=32, seed=24)
            with triplets.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fields = list(reader.fieldnames or [])
            fields += ["vote_status", "confidence"]
            rows[0]["vote_status"] = "tie"
            rows[0]["confidence"] = "1"
            for row in rows[1:]:
                row["vote_status"] = "preference"
                row["confidence"] = "2"
            source = root / "preferences.csv"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader(); writer.writerows(rows)
            first, second = root / "first.csv", root / "second.csv"
            summary = create_splits(source, first, root / "first.json", seed=24)
            self.assertEqual(summary["excluded_tied_rows"], 1)
            for row in rows:
                row["confidence"] = "5"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader(); writer.writerows(rows)
            create_splits(source, second, root / "second.json", seed=24)
            def split_signature(path):
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    return [(row["anchor_id"], row["positive_id"], row["negative_id"], row["split"])
                            for row in csv.DictReader(handle)]
            self.assertEqual(split_signature(first), split_signature(second))
            with first.open(newline="", encoding="utf-8-sig") as handle:
                self.assertNotIn("confidence", csv.DictReader(handle).fieldnames)

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
