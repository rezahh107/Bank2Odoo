# Qt styling mechanism diagnostic probe

This is a standalone diagnostic and does NOT import Bank2Odoo product modules.
It never reads banking data and does not change financial logic.

## Owner Windows 11 local run (PowerShell)

From repository root after the normal one-time uv install:

    uv sync --locked
    $env:QT_QPA_PLATFORM = "windows"
    Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
    uv run --locked python tools/qt_style_probe/probe.py --output "C:\Private\qt-style-probe\native" --scale-tag owner-native

Optional synthetic 150% (not a substitute for Windows display settings):

    $env:QT_SCALE_FACTOR = "1.5"
    uv run --locked python tools/qt_style_probe/probe.py --output "C:\Private\qt-style-probe\synthetic-150" --scale-tag synthetic-150
    Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue

Use a private directory outside the repository; do not commit diagnostic artifacts.

Each run produces {theme}_{style}_{method}_{widget}_{state}.png, with
checkbox_unchecked and checkbox_checked as separate widget types; additional
surface_normal grabs, a contact_sheet_{theme}.png for each theme,
measurements.csv and environment.json, plus checkbox tick assets and
negative-control images. The 2 contact sheets are visual indexes; raw
screenshots and CSV are authoritative for the captured pixels.

Default has no widget-specific palette or stylesheet. All methods receive
the same *controlled application-level theme baseline* for Window, Base,
WindowText, Text so backgrounds are comparable. This experimental baseline
is not proof of native system dark-mode behavior.

Palette changes Button, ButtonText, Highlight, HighlightedText, Window,
Base and Text roles on individual widgets, with an explicit Disabled group.
QSS is widget-local and includes hover, focus, pressed, disabled rules.
Its checkbox indicator uses a local generated image for a real checkmark,
rather than merely filling the indicator rectangle.

NOT_RENDERED means the pixels differ only negligibly from Normal.
APPLIED means measured RGB distance <= 12 from an explicit token.
IGNORED means effectively unchanged from the Default background;
Default itself is labeled IGNORED by convention. PARTIAL means a change
that does not match an exact target. No exact unchecked checkbox indicator
token is provided; those results require visual examination.

Text color samples are clustered high-contrast RGB samples from the label
ROI, NOT necessarily the full rasterized glyph color. Checked indicator
center may sample the checkmark instead of its fill. Contrast ratios are
informational, not accessibility certification. Native shape columns use
mechanism inference and require separate visual inspection.

QTest.mouseMove is attempted first. A failed hover capture triggers an
explicit WA_UnderMouse+Enter simulated fallback. Unchanged states are
NOT_RENDERED even if APIs were invoked. widget.grab() captures widget
painting, not pixels on a physical desktop screen. Font is resolved with
QFontInfo(app.font()); individual Persian glyph fallback is not proven.

Negative controls: an intentionally wrong object-name selector must not
alter the Default rendering; and at least one customized Fusion button
must render materially differently. Failure exits nonzero.

CI runs Windows QPA on windows-latest and windows-2025 at runner-native
scale and synthetic QT_SCALE_FACTOR=1.5. It uploads an artifact named
qt-style-probe-<runner>-<run_id> with both variants. A Windows hosted
runner is not a substitute for the Owner's real Windows 11 desktop.
