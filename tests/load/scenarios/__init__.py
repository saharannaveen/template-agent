"""Locust user scenarios for load testing."""

from tests.load.scenarios.multi_turn import MultiTurnUser
from tests.load.scenarios.single_turn import SingleTurnUser

__all__ = ["SingleTurnUser", "MultiTurnUser"]
