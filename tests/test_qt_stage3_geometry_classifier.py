"""Regression protection for Stage 3 measurement-to-verdict geometry classification."""
from __future__ import annotations

import unittest

from tests import qt_stage3_geometry_classifier as classifier


def record():
    return {
        "state": "saved_success",
        "viewport": [900, 620],
        "content": [900, 1000],
        "horizontal_scroll_max": 0,
        "horizontal_overflow_logical_px": 0,
        "required_controls": ["primary", "approved", "save_folder"],
        "reachable": {
            name: {
                "in_viewport": True,
                "horizontally_contained": True,
                "rectangle": [10, 10, 120, 40],
            } for name in ("primary", "approved", "save_folder")
        },
    }


class Stage3GeometryClassifierTests(unittest.TestCase):
    def assert_unqualified(self, states):
        result = classifier.classify_geometry(states)
        self.assertEqual(result["status"], "NOT_QUALIFIED", result)
        self.assertTrue(result["failure_reasons"])

    def test_partial_horizontal_clipping_fails_even_when_in_viewport(self):
        case = record()
        case["reachable"]["primary"]["horizontally_contained"] = False
        # The former implementation was a false positive for this exact input.
        self.assertTrue(all(
            p is None or p["in_viewport"] for p in case["reachable"].values()
        ))
        self.assert_unqualified([case])
        self.assertFalse(classifier.classify_geometry([case])["all_key_controls_reachable"])

    def test_focused_regression_kills_prior_partial_visibility_mutant(self):
        # Run the same focused regression under the original defective verdict.
        # A regression suite that accepts this mutant has no protection.
        from unittest.mock import patch

        def prior_classifier(states):
            old_reach = all(
                control is None or control["in_viewport"]
                for state in states for control in state["reachable"].values()
            )
            old_overflow = max(state["horizontal_scroll_max"] for state in states)
            return {"status": "GEOMETRY_PASS" if old_reach and not old_overflow
                    else "NOT_QUALIFIED", "failure_reasons": [],
                    "all_key_controls_reachable": old_reach}

        targeted = Stage3GeometryClassifierTests(
            "test_partial_horizontal_clipping_fails_even_when_in_viewport")
        with patch.object(classifier, "classify_geometry", side_effect=prior_classifier):
            result = unittest.TestResult()
            targeted.run(result)
        self.assertEqual(len(result.failures), 1,
                         "The partial-clipping regression must kill the old classifier")
        self.assertEqual(len(result.errors), 0)

    def test_missing_required_control_and_none_are_not_success(self):
        for mutation in ("absent", "none", "no_required_registry",
                         "missing_horizontal_flag", "missing_viewport_flag",
                         "missing_rectangle", "no_reachable_registry"):
            with self.subTest(mutation=mutation):
                case = record()
                if mutation == "absent":
                    del case["reachable"]["approved"]
                elif mutation == "none":
                    case["reachable"]["approved"] = None
                elif mutation == "no_required_registry":
                    del case["required_controls"]
                elif mutation == "missing_horizontal_flag":
                    del case["reachable"]["approved"]["horizontally_contained"]
                elif mutation == "missing_viewport_flag":
                    del case["reachable"]["approved"]["in_viewport"]
                elif mutation == "missing_rectangle":
                    del case["reachable"]["approved"]["rectangle"]
                elif mutation == "no_reachable_registry":
                    del case["reachable"]
                self.assert_unqualified([case])

    def test_complete_horizontal_zero_overflow_passes(self):
        result = classifier.classify_geometry([record()])
        self.assertEqual(result["status"], "GEOMETRY_PASS")
        self.assertTrue(result["all_key_controls_reachable"])
        self.assertEqual(result["failure_reasons"], [])

    def test_failed_state_cannot_be_masked_by_other_good_states(self):
        bad = record()
        bad["state"] = "source_selected"
        bad["reachable"]["approved"]["horizontally_contained"] = False
        self.assert_unqualified([record(), bad, record()])

    def test_500px_existing_negative_remains_unqualified(self):
        case = record()
        case["state"] = "forced_below_native_required"
        case["viewport"] = [486, 620]
        case["content"] = [601, 1000]
        case["horizontal_overflow_logical_px"] = 115
        case["horizontal_scroll_max"] = 115
        self.assert_unqualified([case])

    def test_missing_geometry_or_inconsistent_width_is_not_pass(self):
        for mutation in ("empty_states", "missing_scroll", "missing_dimensions",
                         "hidden_scroll_does_not_hide_clipping", "inconsistent_overflow"):
            with self.subTest(mutation=mutation):
                case = record()
                if mutation == "empty_states":
                    self.assert_unqualified([])
                    continue
                elif mutation == "missing_scroll":
                    del case["horizontal_scroll_max"]
                elif mutation == "missing_dimensions":
                    del case["viewport"]
                elif mutation == "hidden_scroll_does_not_hide_clipping":
                    case["content"][0] = 920
                    case["horizontal_overflow_logical_px"] = 20
                elif mutation == "inconsistent_overflow":
                    case["content"][0] = 920
                self.assert_unqualified([case])


if __name__ == "__main__":
    unittest.main()
