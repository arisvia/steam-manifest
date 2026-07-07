"""
Pytest configuration and shared fixtures for steam-manifest tests.
"""
import asyncio
import sys
from contextlib import suppress

import pytest


def pytest_configure(config):
    """Configure Windows-specific event loop policy."""
    if sys.platform == "win32":
        with suppress(Exception):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class FakeHttpClient:
    """Fake HTTP client for testing async network operations."""

    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.cache = {}
        self.cache_hits = 0

    async def get(self, url, **kwargs):
        if url in self.cache:
            self.cache_hits += 1
            return self.cache[url]
        result = self.mapping.get(url)
        if result is not None:
            self.cache[url] = result
        return result

    async def raw_get(self, url, **kwargs):
        return self.mapping.get(url, b"")

    async def batch_get(self, urls, **kwargs):
        return {url: self.mapping.get(url) for url in urls}


@pytest.fixture
def fake_http_client():
    """Provide a fake HTTP client fixture."""
    return FakeHttpClient()


@pytest.fixture
def mock_steam_config():
    """Provide a minimal Steam configuration fixture."""
    return {
        "steam_path": "/tmp/steam",
        "appid": "480",
        "depots": [],
        "manifests": [],
    }


@pytest.fixture
def mock_github_repo():
    """Provide mock GitHub repository data."""
    return {
        "repo": "SteamAutoCracks/ManifestHub",
        "branch": "main",
        "files": [
            {"path": "480/manifest.txt", "type": "blob"},
            {"path": "480/depot_keys.vdf", "type": "blob"},
        ],
    }
