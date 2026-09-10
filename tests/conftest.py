"""Test-process configuration must be installed before application imports."""

from __future__ import annotations

import os
import tempfile

# Synthetic test values only; no developer credentials or project .env are used.
os.environ["ZHIHU_ACCESS_SECRET"] = "test-only-secret"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="epistree-tests-")
os.environ.pop("LLM_API_KEY", None)
