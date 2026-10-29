# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Fixtures: the tests run on both netlists, functional blocks and gates. One bench per
netlist is built for the whole session, the tests load their programs into it.

--slow also runs the long tests (the C self test on gates, more random seeds).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rv32sim import Bench


MODES = ["functional", "gates"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--slow", action="store_true", help="also run the long tests")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: a long test, run with --slow")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--slow"):
        return
    skip = pytest.mark.skip(reason="a long test, run with --slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


_benches: dict[str, Bench] = {}


@pytest.fixture(params=MODES)
def mode(request: pytest.FixtureRequest) -> str:
    return request.param


def get_bench(mode: str) -> Bench:
    if mode not in _benches:
        _benches[mode] = Bench(b"", functional=mode == "functional")
    return _benches[mode]


@pytest.fixture
def bench(mode: str) -> Bench:
    """The bench of this netlist"""
    return get_bench(mode)


@pytest.fixture
def run(bench: Bench) -> Callable[..., object]:
    """Run a program image in lockstep with the reference model"""

    def run_image(image: bytes, max_cycles: int = 2000, **kwargs: object) -> object:
        bench.load(image)
        return bench.run(max_cycles=max_cycles, lockstep=True, **kwargs)

    return run_image
