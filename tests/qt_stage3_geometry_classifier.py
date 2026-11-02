"""Independent Stage 3 scenario/control contract and fail-closed geometry verdict.

No Qt or production dependency. The collector records observations; this module
determines expected states and widgets without trusting collector-supplied lists.
"""
from __future__ import annotations

WIDTHS = (800, 840, 900, 940, 980)
VARIANTS = ("main_journal", "journal_free")
SCHEMES = ("light", "dark")
CORE_STATES = (
    "initial", "source_selected", "invalid_context", "approval_unchecked",
    "approval_checked", "not_proven", "folder_selected", "saved_success",
)
DECISIVE_STATES = (
    "initial", "source_selected", "invalid_context", "approval_unchecked",
    "approval_checked", "busy", "cancel_requested", "cancel_completed",
    "not_proven", "save_failure", "folder_selected", "saved_success", "pass",
)
RESULT_STATES = ("not_proven", "save_failure", "folder_selected", "saved_success", "pass")
ACTIVE_CANCEL_STATES = ("busy", "cancel_requested")
ALWAYS_VISIBLE = (
    "source", "path_field", "detected", "source_unit", "target_unit",
    "precision", "factor", "approved", "primary", "status",
)
RESULT_VISIBLE = ("balance", "save_folder", "output_directory", "saved_paths")
SAVED_VISIBLE = ("csv_path", "report_path")
# Hidden native save_button is NOT a missing financial action: the contextual
# primary button owns that action; its visibility is still independently checked.
CONDITIONAL_CONTROLS = ("save_button", "cancel_button", *RESULT_VISIBLE, *SAVED_VISIBLE)


def expected_states(width: int) -> tuple[str, ...]:
    if width == 500:  # Deliberate isolated negative, not a candidate.
        return ("forced_below_native_required",)
    if width not in WIDTHS:
        raise ValueError(f"Unknown Stage 3 candidate width: {width}")
    return DECISIVE_STATES if width in (800, 940) else CORE_STATES


def expected_controls(variant: str, state: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if variant not in VARIANTS:
        raise ValueError(f"Unknown interface variant: {variant}")
    if state not in (*DECISIVE_STATES, "forced_below_native_required"):
        raise ValueError(f"Unknown Stage 3 state: {state}")
    visible = list(ALWAYS_VISIBLE)
    if variant == "main_journal":
        visible.append("journal")
    if state in RESULT_STATES:
        visible.extend(RESULT_VISIBLE)
    if state == "saved_success":
        visible.extend(SAVED_VISIBLE)
    if state in ACTIVE_CANCEL_STATES:
        visible.append("cancel_button")
    # The native save_button is intentionally hidden; contextual primary owns
    # saving. The cancellation control is hidden except while converting.
    hidden = ("save_button",) if state in ACTIVE_CANCEL_STATES else ("save_button", "cancel_button")
    return tuple(visible), hidden


def _rect_flags(rect: object, viewport: object):
    if (not isinstance(rect, (list, tuple)) or len(rect) != 4
            or any(type(x) is not int for x in rect)
            or rect[2] <= 0 or rect[3] <= 0):
        return None
    x, y, w, h = rect
    vw, vh = viewport
    intersects = x < vw and x + w > 0 and y < vh and y + h > 0
    horizontal = x >= 0 and x + w <= vw
    vertical = y >= 0 and y + h <= vh
    return intersects, horizontal, vertical


def classify_geometry(states: object, *, variant: str, width: int) -> dict:
    """Fail closed on missing/contradictory evidence, without aborting capture.

    Vertical criterion: each required widget MUST be fully within the viewport
    after programmatic ensureWidgetVisible. This does not prove physical human
    navigation, text glyph readability, or simultaneous screen visibility.
    """
    failures: list[str] = []
    reachable_ok = True
    geometry_ok = True

    try:
        required_states = expected_states(width)
        if variant not in VARIANTS:
            raise ValueError(variant)
    except (ValueError, TypeError):
        return {"status": "NOT_QUALIFIED", "all_key_controls_reachable": False,
                "failure_reasons": ["unknown_variant_or_width"],
                "vertical_visibility_standard": "fully_contained_after_programmatic_scroll"}

    if not isinstance(states, list) or not states:
        return {"status": "NOT_QUALIFIED", "all_key_controls_reachable": False,
                "failure_reasons": ["missing_states"],
                "vertical_visibility_standard": "fully_contained_after_programmatic_scroll"}

    found = [s.get("state") if isinstance(s, dict) else None for s in states]
    if len(found) != len(required_states) or found != list(required_states):
        failures.append("missing_extra_duplicate_or_out_of_order_states")
        geometry_ok = reachable_ok = False

    for index, state in enumerate(states):
        label = state.get("state", index) if isinstance(state, dict) else index
        prefix = f"{label}:"
        if not isinstance(state, dict) or label not in required_states:
            failures.append(prefix + "unknown_or_missing_state")
            geometry_ok = reachable_ok = False
            continue

        viewport, content = state.get("viewport"), state.get("content")
        valid_dims = (
            isinstance(viewport, (list, tuple)) and len(viewport) == 2
            and isinstance(content, (list, tuple)) and len(content) == 2
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
        if state.get("layout") != "LeftToRight":
            failures.append(prefix + "not_fixed_two_column_layout")
            geometry_ok = False

        expected_visible, expected_hidden = expected_controls(variant, label)
        observed_required = state.get("required_controls")
        visible = state.get("control_visibility")
        presence = state.get("control_presence")
        measured = state.get("reachable")
        required_names = set(expected_visible)
        hidden_names = set(expected_hidden)
        known_names = set((*ALWAYS_VISIBLE, "journal", *CONDITIONAL_CONTROLS))
        contract_names = known_names - ({"journal"} if variant == "journal_free" else set())
        if (not isinstance(observed_required, list)
                or len(observed_required) != len(set(observed_required))
                or not required_names.issubset(set(observed_required))):
            failures.append(prefix + "required_control_registry_mismatch")
            reachable_ok = False
        if not isinstance(visible, dict) or not isinstance(measured, dict):
            failures.append(prefix + "missing_control_observations")
            reachable_ok = False
            continue
        if not isinstance(presence, dict) or set(presence) != known_names:
            failures.append(prefix + "missing_control_presence_observations")
            reachable_ok = False
        if set(visible) != contract_names:
            failures.append(prefix + "control_visibility_registry_mismatch")
            reachable_ok = False
        if (isinstance(observed_required, list) and
                (set(measured) != set(observed_required)
                 or {k for k, v in visible.items() if v is True} != set(observed_required))):
            failures.append(prefix + "reachability_registry_mismatch")
            reachable_ok = False
        if isinstance(presence, dict):
            for name in contract_names:
                if presence.get(name) is not True:
                    failures.append(prefix + name + ":missing_widget")
                    reachable_ok = False
            if presence.get("journal") is not (variant == "main_journal"):
                failures.append(prefix + "journal_presence_mismatch")
                reachable_ok = False

        for name in expected_hidden:
            if visible.get(name) is not False:
                failures.append(prefix + name + ":expected_hidden_or_inapplicable")
                reachable_ok = False
        for name in expected_visible:
            if visible.get(name) is not True:
                failures.append(prefix + name + ":expected_visible")
                reachable_ok = False
        # Also verify any other visible control instead of trusting an
        # observer-controlled list to exclude inconvenient geometry.
        for name in (observed_required if isinstance(observed_required, list) else expected_visible):
            info = measured.get(name)
            if not isinstance(info, dict):
                failures.append(prefix + name + ":missing_reachability")
                reachable_ok = False
                continue
            if not valid_dims:
                failures.append(prefix + name + ":unverifiable_rectangle")
                reachable_ok = False
                continue
            calculated = _rect_flags(info.get("rectangle"), viewport)
            if calculated is None:
                failures.append(prefix + name + ":invalid_rectangle")
                reachable_ok = False
                continue
            for field, expected in zip(
                    ("in_viewport", "horizontally_contained", "vertically_contained"),
                    calculated):
                if info.get(field) is not expected:
                    failures.append(prefix + name + ":contradictory_" + field)
                    reachable_ok = False
            if not all(calculated):
                failures.append(prefix + name + ":partial_or_unreachable")
                reachable_ok = False

    return {
        "status": "GEOMETRY_PASS" if geometry_ok and reachable_ok and not failures else "NOT_QUALIFIED",
        "all_key_controls_reachable": reachable_ok,
        "failure_reasons": failures,
        "vertical_visibility_standard": "fully_contained_after_programmatic_scroll",
    }
