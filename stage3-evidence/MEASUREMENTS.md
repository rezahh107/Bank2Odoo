# Stage 3 Windows Qt QPA measurements (not physical desktop approval)

Source main: `e0f50ab8605024896bf6975050fb4034b874514e`; PR20: `aa4362adfa8cd3e6e2873c8b36de79ce8183e3bd`.
Light uses test-set Qt Light hint and native-style branch; Dark uses a test-set Dark hint and simulated Fusion palette. Both have authentic QWidget grabs on a Windows hosted runner.
Comparison configuration overrides only the live test window's reflow to two columns; production stays unchanged. Logical pixels; PNG dimensions and Qt DPR recorded per capture.
GEOMETRY_PASS is assigned only by tests.qt_stage3_geometry_classifier.classify_geometry over every required control in every measured state; missing and partially clipped controls fail closed.

| Variant | Scheme | Minimum width | Max required | Viewport | Max horizontal scrollbar overflow | All key controls reachable | Geometry status |
|---|---|---:|---:|---:|---:|---|---|
| main_journal | light | 800 | 724 | 788 | 0 | True | GEOMETRY_PASS |
| main_journal | light | 840 | 724 | 828 | 0 | True | GEOMETRY_PASS |
| main_journal | light | 900 | 724 | 888 | 0 | True | GEOMETRY_PASS |
| main_journal | light | 940 | 724 | 928 | 0 | True | GEOMETRY_PASS |
| main_journal | light | 980 | 724 | 968 | 0 | True | GEOMETRY_PASS |
| main_journal | dark | 800 | 712 | 786 | 0 | True | GEOMETRY_PASS |
| main_journal | dark | 840 | 712 | 826 | 0 | True | GEOMETRY_PASS |
| main_journal | dark | 900 | 712 | 886 | 0 | True | GEOMETRY_PASS |
| main_journal | dark | 940 | 712 | 926 | 0 | True | GEOMETRY_PASS |
| main_journal | dark | 980 | 712 | 966 | 0 | True | GEOMETRY_PASS |
| journal_free | light | 800 | 724 | 788 | 0 | True | GEOMETRY_PASS |
| journal_free | light | 840 | 724 | 828 | 0 | True | GEOMETRY_PASS |
| journal_free | light | 900 | 724 | 888 | 0 | True | GEOMETRY_PASS |
| journal_free | light | 940 | 724 | 928 | 0 | True | GEOMETRY_PASS |
| journal_free | light | 980 | 724 | 968 | 0 | True | GEOMETRY_PASS |
| journal_free | dark | 800 | 712 | 786 | 0 | True | GEOMETRY_PASS |
| journal_free | dark | 840 | 712 | 826 | 0 | True | GEOMETRY_PASS |
| journal_free | dark | 900 | 712 | 886 | 0 | True | GEOMETRY_PASS |
| journal_free | dark | 940 | 712 | 926 | 0 | True | GEOMETRY_PASS |
| journal_free | dark | 980 | 712 | 966 | 0 | True | GEOMETRY_PASS |

Negative forced 500 px: scrollbar overflow = 115 logical px; classification = NOT_QUALIFIED.
Visual readability/density, physical DPI scaling (100/125/150%), real OS theme and target-accountant acceptance remain NOT_PROVEN pending specialist review.
Screenshots are genuine, unmodified QWidget.grab PNGs; contact sheets are preview composites only.
