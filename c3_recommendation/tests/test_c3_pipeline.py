"""Focused tests for the Component 3 retrieval prototype."""

from __future__ import annotations

import unittest

import numpy as np

from c3_recommendation.pipeline import (
    audio_ranked_pool,
    baseline_results,
    choose_evaluation_indexes,
    mmr_results,
    parameter_distance,
    recommendation_metrics,
)


class _Candidate:
    def __init__(self, sample_index: int) -> None:
        self.sample_index = sample_index


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.features = np.asarray(
            [
                [1.0, 0.0],
                [0.99, 0.10],
                [0.98, 0.20],
                [0.90, 0.44],
                [0.80, 0.60],
            ],
            dtype=np.float64,
        )
        self.features /= np.linalg.norm(self.features, axis=1, keepdims=True)
        self.candidates = [_Candidate(index) for index in range(len(self.features))]
        self.parameters = np.asarray(
            [
                [0.0, 0.0],
                [0.02, 0.02],
                [0.04, 0.04],
                [0.06, 0.06],
                [1.0, 1.0],
            ],
            dtype=np.float64,
        )

    def test_audio_ranking_excludes_query(self) -> None:
        indexes, similarities = audio_ranked_pool(
            self.features[0], self.features, self.candidates, 4, 0
        )
        np.testing.assert_array_equal(indexes, [1, 2, 3, 4])
        self.assertTrue(np.all(similarities[:-1] >= similarities[1:]))

    def test_lambda_one_matches_audio_top_k(self) -> None:
        indexes, similarities = audio_ranked_pool(
            self.features[0], self.features, self.candidates, 4, 0
        )
        baseline = baseline_results(indexes, similarities, 3)
        reranked = mmr_results(indexes, similarities, self.parameters, 3, 1.0)
        self.assertEqual(
            [result.candidate_index for result in baseline],
            [result.candidate_index for result in reranked],
        )

    def test_mmr_can_increase_parameter_diversity(self) -> None:
        indexes, similarities = audio_ranked_pool(
            self.features[0], self.features, self.candidates, 4, 0
        )
        baseline = baseline_results(indexes, similarities, 3)
        reranked = mmr_results(indexes, similarities, self.parameters, 3, 0.5)
        baseline_metrics = recommendation_metrics(baseline, self.parameters, None)
        reranked_metrics = recommendation_metrics(reranked, self.parameters, None)
        self.assertGreater(
            reranked_metrics["mean_pairwise_parameter_distance"],
            baseline_metrics["mean_pairwise_parameter_distance"],
        )


class DeterminismTests(unittest.TestCase):
    def test_evaluation_queries_are_reproducible(self) -> None:
        first = choose_evaluation_indexes(1024, 32, 20260826)
        second = choose_evaluation_indexes(1024, 32, 20260826)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(len(np.unique(first)), 32)

    def test_parameter_distance_is_range_normalized(self) -> None:
        self.assertAlmostEqual(
            parameter_distance(np.zeros(8), np.ones(8)), 1.0
        )


if __name__ == "__main__":
    unittest.main()
