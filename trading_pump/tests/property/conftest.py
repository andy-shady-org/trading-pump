"""Hypothesis settings for ``tests/property/``.

Property tests are derandomized so a run is reproducible on every machine and
in CI (the suite is deterministic, see docs/dev/TESTING.md); set
``HYPOTHESIS_PROFILE=explore`` locally to search with fresh random seeds.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "deterministic",
    derandomize=True,
    database=None,
    deadline=None,
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("explore", deadline=None, max_examples=2_000)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "deterministic"))
