"""Adversarial tests for independently specified Stage 3 evidence integrity."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from tests import qt_stage3_geometry_classifier as g


def state(stage, *, variant="journal_free"):
    visible, hidden = g.expected_controls(variant, stage)
    names = set((*g.ALWAYS_VISIBLE, "journal", *g.CONDITIONAL_CONTROLS))
    presence = {name: (name != "journal" or variant == "main_journal") for name in names}
    visibility = {name: name in visible for name in names if presence[name]}
    return {
        "state": stage, "layout": "LeftToRight",
        "viewport": [900, 620], "content": [900, 1100],
        "horizontal_overflow_logical_px": 0, "horizontal_scroll_max": 0,
        "required_controls": list(visible),
        "control_presence": presence, "control_visibility": visibility,
        "reachable": {name: {
            "in_viewport": True, "horizontally_contained": True,
            "vertically_contained": True, "rectangle": [10, 10, 120, 40],
        } for name in visible},
    }


def candidate(*, variant="journal_free", width=800):
    return [state(name, variant=variant) for name in g.expected_states(width)]


class Stage3IntegrityTests(unittest.TestCase):
    def assert_rejected(self, entries, variant="journal_free", width=800):
        result = g.classify_geometry(entries, variant=variant, width=width)
        self.assertEqual(result["status"], "NOT_QUALIFIED", result)
        self.assertTrue(result["failure_reasons"])
        return result

    def test_positive_complete_800_and_non_decisive_matrix(self):
        for variant in g.VARIANTS:
            for width in g.WIDTHS:
                with self.subTest(variant=variant, width=width):
                    result = g.classify_geometry(candidate(variant=variant, width=width),
                                                 variant=variant, width=width)
                    self.assertEqual(result["status"], "GEOMETRY_PASS", result)
                    self.assertTrue(result["all_key_controls_reachable"])

    def test_partial_vertical_clipping_fails_despite_intersection(self):
        entries = candidate()
        entries[0]["reachable"]["approved"].update(
            rectangle=[10, 600, 120, 40],
            in_viewport=True, vertically_contained=False,
        )
        self.assert_rejected(entries)

    def test_rectangle_inconsistent_with_horizontal_and_vertical_flags(self):
        for rect, name, flag in (([-4, 10, 120, 40], "factor", "horizontally_contained"),
                                 ([10, 600, 120, 40], "approved", "vertically_contained"),
                                 ([10, 700, 120, 40], "primary", "in_viewport")):
            with self.subTest(rect=rect):
                entries = candidate()
                entries[0]["reachable"][name]["rectangle"] = rect
                # Deliberately retain True flags from an otherwise valid state.
                result = self.assert_rejected(entries)
                self.assertTrue(any("contradictory_" + flag in x
                                    for x in result["failure_reasons"]), result)

    def test_missing_save_action_and_financial_context_cannot_pass(self):
        for name, stage in (("save_folder", "saved_success"),
                            ("output_directory", "folder_selected"),
                            ("source_unit", "approval_checked"),
                            ("factor", "invalid_context"),
                            ("precision", "source_selected")):
            with self.subTest(name=name, stage=stage):
                entries = candidate()
                item = next(x for x in entries if x["state"] == stage)
                item["required_controls"].remove(name)
                item["reachable"].pop(name)
                item["control_visibility"].pop(name)
                self.assert_rejected(entries)

    def test_missing_cancel_and_hidden_native_save_control_proof(self):
        entries = candidate()
        busy = next(x for x in entries if x["state"] == "busy")
        busy["required_controls"].remove("cancel_button")
        busy["reachable"].pop("cancel_button")
        busy["control_visibility"].pop("cancel_button")
        self.assert_rejected(entries)

        entries = candidate()
        entries[0]["control_presence"].pop("save_button")
        entries[0]["control_visibility"].pop("save_button")
        self.assert_rejected(entries)

        entries = candidate()
        entries[0]["control_visibility"]["save_button"] = True
        self.assert_rejected(entries)

    def test_true_inapplicable_controls_not_counted_as_missing(self):
        entries = candidate()
        first = entries[0]
        self.assertFalse(first["control_visibility"]["save_button"])
        self.assertFalse(first["control_visibility"]["cancel_button"])
        self.assertNotIn("save_button", first["reachable"])
        self.assertNotIn("cancel_button", first["reachable"])
        self.assertEqual(g.classify_geometry(entries, variant="journal_free",
                                            width=800)["status"], "GEOMETRY_PASS")

    def test_missing_required_state_and_mixed_valid_invalid(self):
        entries = candidate()
        self.assert_rejected([x for x in entries if x["state"] != "busy"])
        self.assert_rejected(entries[:-1])
        entries = candidate()
        entries[-2]["reachable"]["primary"]["horizontally_contained"] = False
        self.assert_rejected(entries)
        entries = candidate()
        entries.insert(1, copy.deepcopy(entries[0]))
        self.assert_rejected(entries)

    def test_missing_or_falsified_geometry_never_passes(self):
        for mutation in ("missing_reachable", "none", "missing_rect",
                         "zero_viewport", "missing_scroll", "hidden_overflow",
                         "contradictory_horizontal", "missing_required_registry"):
            with self.subTest(mutation=mutation):
                entries = candidate()
                item = entries[0]
                if mutation == "missing_reachable":
                    item["reachable"].pop("approved")
                elif mutation == "none":
                    item["reachable"]["approved"] = None
                elif mutation == "missing_rect":
                    item["reachable"]["approved"].pop("rectangle")
                elif mutation == "zero_viewport":
                    item["viewport"][0] = 0
                elif mutation == "missing_scroll":
                    item.pop("horizontal_scroll_max")
                elif mutation == "hidden_overflow":
                    item["content"][0] = 925
                    item["horizontal_overflow_logical_px"] = 25
                elif mutation == "contradictory_horizontal":
                    item["content"][0] = 925
                elif mutation == "missing_required_registry":
                    item.pop("required_controls")
                self.assert_rejected(entries)

    def test_500px_native_negative_remains_not_qualified(self):
        negative = state("forced_below_native_required")
        negative.update(viewport=[486, 620], content=[601, 1100],
                        horizontal_overflow_logical_px=115, horizontal_scroll_max=115)
        negative["reachable"]["primary"]["rectangle"] = [-6, 10, 120, 40]
        negative["reachable"]["primary"]["horizontally_contained"] = False
        self.assert_rejected([negative], width=500)

    def test_original_partial_visibility_classifier_mutant_is_detected(self):
        entries = candidate()
        entries[0]["reachable"]["approved"]["rectangle"] = [-6, 10, 120, 40]
        entries[0]["reachable"]["approved"]["horizontally_contained"] = False

        def original_defective_classifier(states, *, variant, width):
            # Before this repair: already-recorded booleans were trusted and
            # all partial vertical intersections were called reachable.
            ok = all(p is None or p["in_viewport"]
                     for s in states for p in s["reachable"].values())
            overflow = max(s["horizontal_scroll_max"] for s in states)
            return {"status": "GEOMETRY_PASS" if ok and not overflow
                    else "NOT_QUALIFIED", "failure_reasons": [],
                    "all_key_controls_reachable": ok}

        def reject_partial():
            self.assert_rejected(entries)

        with patch.object(g, "classify_geometry", side_effect=original_defective_classifier):
            result = unittest.TestResult()
            class Replay(unittest.TestCase):
                def runTest(self_inner):
                    reject_partial()
            Replay().run(result)
        self.assertEqual(len(result.failures), 1,
                         "The original defective classifier must fail this test")
        self.assertEqual(result.errors, [])

    def test_weak_flags_only_classifier_mutant_is_detected(self):
        entries = candidate()
        entries[0]["reachable"]["approved"]["rectangle"] = [-6, 10, 120, 40]
        # Stale True flags now contradict the rectangle.
        self.assert_rejected(entries)


if __name__ == "__main__":
    unittest.main()
