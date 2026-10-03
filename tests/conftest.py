"""Shared test settings."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_signing_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never sign with the developer's own SSH key; signing tests set their own."""
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
