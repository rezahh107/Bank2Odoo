"""Fail-closed Stage 3 geometry verdicts over measured Qt evidence only.

No UI policy or Qt dependency: this is the single measurement-to-verdict boundary.
"""
from __future__ import annotations


def classify_geometry(states: object) -> dict:
    """A PASS requires complete geometry and every measured required control.

    `required_controls` is captured alongside `reachable` by the Qt probe,
    not independently restated in the report. Old/incomplete manifests fail closed.
    A failing candidate still returns a verdict; it never interrupts collection.
    """
    failures: list[str] = []
    controls_ok = True
    geometry_ok = True

    if not isinstance(states, list) or not states:
        return {
            "status": "NOT_QUALIFIED",
            "all_key_controls_reachable": False,
            "failure_reasons": ["missing_states"],
        }

    for index, state in enumerate(states):
        stage = state.get("state", index) if isinstance(state, dict) else index
        prefix = f"{stage}:"
        if not isinstance(state, dict):
            failures.append(prefix + "missing_state_measurements")
            controls_ok = geometry_ok = False
            continue

        viewport = state.get("viewport")
        content = state.get("content")
        valid_dims = (
            isinstance(viewport, (tuple, list)) and len(viewport) == 2
            and isinstance(content, (tuple, list)) and len(content) == 2
            and all(type(v) is int and v > 0 for v in (*viewport, *content))
        )
        if not valid_dims:
            failures.append(prefix + "missing_or_invalid_dimensions")
            geometry_ok = False

        scroll = state.get("horizontal_scroll_max")
        overflow = state.get("horizontal_overflow_logical_px")
        if (type(scroll) is not int or scroll != 0
                or type(overflow) is not int or overflow != 0
                or (valid_dims and overflow != max(0, content[0] - viewport[0]))):
            failures.append(prefix + "missing_inconsistent_or_positive_overflow")
            geometry_ok = False

        required = state.get("required_controls")
        reachable = state.get("reachable")
        valid_registry = (
            isinstance(required, list) and bool(required)
            and all(isinstance(k, str) and bool(k) for k in required)
            and len(required) == len(set(required))
            and isinstance(reachable, dict)
        )
        if not valid_registry:
            failures.append(prefix + "missing_or_invalid_required_controls")
            controls_ok = False
            continue

        for name in required:
            info = reachable.get(name)
            if not isinstance(info, dict):
                failures.append(prefix + name + ":missing_reachability")
                controls_ok = False
                continue
            rectangle = info.get("rectangle")
            has_rectangle = (
                isinstance(rectangle, (list, tuple)) and len(rectangle) == 4
                and all(type(v) is int for v in rectangle)
                and rectangle[2] > 0 and rectangle[3] > 0
            )
            if not has_rectangle or info.get("in_viewport") is not True:
                failures.append(prefix + name + ":not_in_viewport_or_invalid_rectangle")
                controls_ok = False
            if info.get("horizontally_contained") is not True:
                failures.append(prefix + name + ":not_horizontally_contained")
                controls_ok = False

    return {
        "status": "GEOMETRY_PASS" if geometry_ok and controls_ok else "NOT_QUALIFIED",
        "all_key_controls_reachable": controls_ok,
        "failure_reasons": failures,
    }
