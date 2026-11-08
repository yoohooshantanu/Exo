"""Tests for deterministic orbital trial seeds."""
from modules.orbital_gap_predictor import _trial_seed


class TestTrialSeed:
    def test_stable_across_calls(self):
        a = _trial_seed(42, "star-1", 0, "2:1 MMR inner", 3)
        b = _trial_seed(42, "star-1", 0, "2:1 MMR inner", 3)
        assert a == b

    def test_differs_by_trial_index(self):
        a = _trial_seed(42, "star-1", 0, "2:1 MMR inner", 1)
        b = _trial_seed(42, "star-1", 0, "2:1 MMR inner", 2)
        assert a != b
