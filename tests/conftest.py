from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def secure_test_umask() -> Iterator[None]:
    """Create every test-owned filesystem fixture with owner-only defaults."""
    previous = os.umask(0o077)
    try:
        yield
    finally:
        _ = os.umask(previous)
