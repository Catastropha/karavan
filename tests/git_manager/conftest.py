"""Git manager test fixtures — mock subprocess, GitHub client, and response helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.resource import res


@pytest.fixture
def make_response():
    """Factory for mock httpx responses."""

    def _make(data, status_code=200):
        resp = MagicMock()
        resp.json.return_value = data
        resp.status_code = status_code
        resp.raise_for_status.return_value = None
        return resp

    return _make


@pytest.fixture
def github_client(monkeypatch):
    """Replace res.github_client with an AsyncMock for isolated PR testing."""
    client = AsyncMock()
    monkeypatch.setattr(res, "github_client", client)
    return client


@pytest.fixture
def mock_process():
    """Factory for mock asyncio subprocess results."""

    def _make(returncode=0, stdout=b"", stderr=b""):
        proc = AsyncMock()
        proc.returncode = returncode
        proc.communicate.return_value = (stdout, stderr)
        return proc

    return _make
