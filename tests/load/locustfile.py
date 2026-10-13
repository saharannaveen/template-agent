"""Main Locust entry point for template-agent load testing.

Combines single-turn and multi-turn HTTP scenarios with a 70/30
traffic split.  The graph benchmark runs separately (see
``graph_benchmark.py``).

Load profiles are configured via the ``LOAD_PROFILE`` environment
variable:

    LOAD_PROFILE=smoke locust -f tests/load/locustfile.py

Available profiles:
    - **smoke**: 5 users, 1/s spawn, 2 min — verify the test works
    - **baseline**: 50 users, 1/s spawn, 10 min — establish p50/p95/p99
    - **stress**: 200 users, 2/s spawn, 15 min — find breaking points
    - **soak**: 50 users, 1/s spawn, 30 min — detect memory leaks

Usage examples:

    # Run with defaults (smoke profile)
    locust -f tests/load/locustfile.py --host http://localhost:8123

    # Headless baseline run with CSV output
    LOAD_PROFILE=baseline locust -f tests/load/locustfile.py \\
        --headless --host http://localhost:8123 \\
        --csv tests/load/reports/baseline

    # Override profile settings via CLI
    locust -f tests/load/locustfile.py \\
        --host http://localhost:8123 \\
        -u 100 -r 5 -t 5m
"""

import logging
import os

from locust import events

from tests.load.scenarios.multi_turn import MultiTurnUser
from tests.load.scenarios.single_turn import SingleTurnUser

logger = logging.getLogger(__name__)

# ── Load profiles ───────────────────────────────────────────────

LOAD_PROFILES = {
    "smoke": {"users": 5, "spawn_rate": 1, "run_time": "2m"},
    "baseline": {"users": 50, "spawn_rate": 1, "run_time": "10m"},
    "stress": {"users": 200, "spawn_rate": 2, "run_time": "15m"},
    "soak": {"users": 50, "spawn_rate": 1, "run_time": "30m"},
}

# ── Event hooks ─────────────────────────────────────────────────


@events.init.add_listener
def on_init(environment, **kwargs):  # type: ignore[no-untyped-def]
    """Log the active load profile on Locust startup."""
    profile_name = os.environ.get("LOAD_PROFILE", "smoke")
    profile = LOAD_PROFILES.get(profile_name)

    if profile is None:
        logger.warning(
            "Unknown LOAD_PROFILE '%s', falling back to 'smoke'. Valid profiles: %s",
            profile_name,
            ", ".join(sorted(LOAD_PROFILES)),
        )
        profile_name = "smoke"
        profile = LOAD_PROFILES[profile_name]

    logger.info(
        "Load test initializing with profile '%s': "
        "users=%d, spawn_rate=%d, run_time=%s",
        profile_name,
        profile["users"],
        profile["spawn_rate"],
        profile["run_time"],
    )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):  # type: ignore[no-untyped-def]
    """Log when the test run begins."""
    logger.info(
        "Load test started. Target host: %s",
        environment.host or "not set",
    )


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):  # type: ignore[no-untyped-def]
    """Log summary when the test run ends."""
    stats = environment.stats
    logger.info(
        "Load test complete. Total requests: %d, failures: %d",
        stats.num_requests,
        stats.num_failures,
    )


# Re-export user classes so Locust discovers them in this module.
# Weights are set on the classes: SingleTurnUser=7, MultiTurnUser=3
# giving a 70/30 traffic split.
__all__ = ["SingleTurnUser", "MultiTurnUser"]
