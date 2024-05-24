# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from .helpers import NUM_UNITS


def pytest_addoption(parser):
    """Parse additional pytest options."""
    parser.addoption("--num-units", action="store", type=int, default=NUM_UNITS)
