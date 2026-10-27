"""Application version shared by CLI and private control-report provenance.

Keep this value aligned with pyproject.toml [project].version; the regression
suite enforces the match. uv package=false means installed-package metadata
cannot be assumed at runtime.
"""

VERSION = "0.2.0"
