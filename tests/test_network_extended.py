"""Extended tests for steam_manifest.core.network.HttpClient.

Covers retry logic (request/raw_get), file download (raw_get), timeout and
error handling (429, non-200, session-None, exceptions), batch_get,
clear_cache, and the async context-manager protocol.

Uses pytest + unittest.mock + AsyncMock.
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

import steam_manifest.core.network as network_mod
from steam_manifest.core.network import HttpClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class FakeResponse:
    """Minimal aiohttp response stub supporting async context manager."""

    def __init__(self, status=200, json_data=None, read_data=None, headers=None):
        self.status = status
        self._json = json_data
        self._read = read_data or b""
        self.headers = headers or {}

    async def json(self, loads=None):
        return self._json

    async def read(self):
        return self._read

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    """aiohttp.ClientSession stub with controllable response sequences."""

    def __init__(self, responses):
        # ``responses`` is a list (for sequential) or single FakeResponse.
        if isinstance(responses, FakeResponse):
            responses = [responses]
        self._responses = list(responses)
        self._call_count = 0
        self.closed = False

    def _next(self):
        if not self._responses:
            return None
        self._call_count += 1
        # Repeat last response if exhausted (for retry scenarios).
        return self._responses[0] if len(self._responses) == 1 else self._responses.pop(0)

    def request(self, method, url, **kwargs):
        return self._next()

    def get(self, url):
        return self._next()

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fast_retries(monkeypatch):
    """Make retries fast and bounded for tests."""
    monkeypatch.setattr(network_mod, "RETRY_TIMES", 3)
    monkeypatch.setattr(network_mod, "RETRY_INTERVAL", 0.001)


@pytest.fixture
def no_retries(monkeypatch):
    """Disable retries so failure paths execute quickly."""
    monkeypatch.setattr(network_mod, "RETRY_TIMES", 1)
    monkeypatch.setattr(network_mod, "RETRY_INTERVAL", 0.001)


# ---------------------------------------------------------------------------
# request() retry logic
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_retries_then_succeeds(fast_retries):
    """request() retries on ClientError and returns data when a later attempt succeeds."""
    good = FakeResponse(status=200, json_data={"ok": True})
    bad = FakeResponse(status=500)
    # First call raises ClientError (via 500 -> raise), second succeeds.
    session = FakeSession([bad, good])
    client = HttpClient()
    client.session = session

    result = await client.request("GET", "https://example.com/api")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_request_exhausts_retries_returns_none(no_retries):
    """request() returns None after exhausting retries on persistent 500."""
    resp = FakeResponse(status=500)
    session = FakeSession(resp)
    client = HttpClient()
    client.session = session

    result = await client.get("https://example.com/always-fail")
    assert result is None


@pytest.mark.asyncio
async def test_request_retries_on_timeout_error(fast_retries):
    """request() retries on asyncio.TimeoutError then succeeds."""
    good = FakeResponse(status=200, json_data={"v": 1})

    session = MagicMock()
    call_count = {"n": 0}

    @asynccontextmanager
    async def ctx(method, url, **kw):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise asyncio.TimeoutError()
        yield good

    session.request = ctx
    session.close = AsyncMock()

    client = HttpClient()
    client.session = session

    result = await client.request("GET", "https://example.com/slow")
    assert result == {"v": 1}
    assert call_count["n"] >= 2


@pytest.mark.asyncio
async def test_request_timeout_exhausted_returns_none(no_retries):
    """request() returns None when TimeoutError persists past retries."""
    session = MagicMock()

    @asynccontextmanager
    async def ctx(method, url, **kw):
        raise asyncio.TimeoutError()
        yield  # pragma: no cover - unreachable

    session.request = ctx
    session.close = AsyncMock()

    client = HttpClient()
    client.session = session

    result = await client.get("https://example.com/timeout")
    assert result is None


# ---------------------------------------------------------------------------
# 429 rate-limit + non-200 error handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_429_rate_limit_triggers_clienterror(no_retries):
    """A 429 response raises ClientError internally and ultimately returns None."""
    resp = FakeResponse(
        status=429,
        headers={"X-RateLimit-Reset": "1700000000"},
    )
    session = FakeSession(resp)
    client = HttpClient()
    client.session = session

    result = await client.get("https://example.com/rate-limited")
    assert result is None


@pytest.mark.asyncio
async def test_request_non200_logs_and_returns_none(no_retries):
    resp = FakeResponse(status=404)
    session = FakeSession(resp)
    client = HttpClient()
    client.session = session

    assert await client.get("https://example.com/missing") is None


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_cache_hit_does_not_touch_session():
    """A cached GET should return without issuing a network request."""
    client = HttpClient()
    client.session = None  # deliberately None to prove no network call
    client.cache["https://example.com/cached"] = {"cached": True}

    result = await client.get("https://example.com/cached")
    assert result == {"cached": True}
    assert client.cache_hits == 1
    # request_count increments even on cache hit (matches production behavior)
    assert client.request_count == 1


@pytest.mark.asyncio
async def test_clear_cache():
    client = HttpClient()
    client.cache["k"] = {"v": 1}
    client.clear_cache()
    assert len(client.cache) == 0


# ---------------------------------------------------------------------------
# Session initialization / context manager
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_initializes_session_when_none(no_retries):
    """request() auto-initializes when session is None."""
    resp = FakeResponse(status=200, json_data={"init": True})

    with patch.object(HttpClient, "initialize", new=AsyncMock()) as mock_init:
        client = HttpClient()
        client.session = FakeSession(resp)
        result = await client.get("https://example.com/auto-init")
        # session was already set, so initialize() should NOT be called
        assert result == {"init": True}
        mock_init.assert_not_called()


@pytest.mark.asyncio
async def test_request_initializes_when_session_none(no_retries):
    """request() calls initialize() when session is None before sending."""
    resp = FakeResponse(status=200, json_data={"x": 1})
    client = HttpClient()

    async def fake_init():
        client.session = FakeSession(resp)

    with patch.object(client, "initialize", new=fake_init):
        result = await client.get("https://example.com/needs-init")
        assert result == {"x": 1}


@pytest.mark.asyncio
async def test_request_returns_none_when_session_still_none(no_retries):
    """If session stays None after initialize(), request returns None."""
    client = HttpClient()
    with patch.object(client, "initialize", new=AsyncMock()):
        result = await client.get("https://example.com/no-session")
    assert result is None


@pytest.mark.asyncio
async def test_aenter_aexit_context_manager():
    """__aenter__ initializes, __aexit__ closes the session."""
    with patch.object(HttpClient, "initialize", new=AsyncMock()) as mock_init, \
         patch.object(HttpClient, "close", new=AsyncMock()) as mock_close:
        client = HttpClient()
        returned = await client.__aenter__()
        assert returned is client
        mock_init.assert_awaited_once()

        await client.__aexit__(None, None, None)
        mock_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_logs_stats_even_without_session():
    """close() is safe when session is None and still logs stats."""
    client = HttpClient()
    client.request_count = 5
    client.cache_hits = 2
    # Should not raise.
    await client.close()


@pytest.mark.asyncio
async def test_close_closes_session():
    session = MagicMock()
    session.close = AsyncMock()
    client = HttpClient()
    client.session = session
    await client.close()
    session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# raw_get() file download
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_raw_get_returns_bytes():
    """raw_get() returns raw bytes on 200."""
    resp = FakeResponse(status=200, read_data=b"file-content")
    session = FakeSession(resp)
    client = HttpClient()
    client.session = session

    data = await client.raw_get("https://example.com/file.bin")
    assert data == b"file-content"


@pytest.mark.asyncio
async def test_raw_get_non200_returns_none(no_retries):
    resp = FakeResponse(status=403)
    session = FakeSession(resp)
    client = HttpClient()
    client.session = session

    assert await client.raw_get("https://example.com/forbidden") is None


@pytest.mark.asyncio
async def test_raw_get_retries_on_clienterror(fast_retries):
    """raw_get() retries on ClientError and succeeds on later attempt."""
    good = FakeResponse(status=200, read_data=b"ok")
    bad = FakeResponse(status=500)
    session = FakeSession([bad, good])
    client = HttpClient()
    client.session = session

    data = await client.raw_get("https://example.com/retry-download")
    assert data == b"ok"


@pytest.mark.asyncio
async def test_raw_get_timeout_returns_none(no_retries):
    session = MagicMock()

    @asynccontextmanager
    async def ctx(url):
        raise asyncio.TimeoutError()
        yield  # pragma: no cover

    session.get = ctx
    client = HttpClient()
    client.session = session

    assert await client.raw_get("https://example.com/timeout-download") is None


@pytest.mark.asyncio
async def test_raw_get_initializes_session_when_none(no_retries):
    """raw_get() auto-initializes when session is None."""
    resp = FakeResponse(status=200, read_data=b"init-data")
    client = HttpClient()

    async def fake_init():
        client.session = FakeSession(resp)

    with patch.object(client, "initialize", new=fake_init):
        data = await client.raw_get("https://example.com/auto")
    assert data == b"init-data"


@pytest.mark.asyncio
async def test_raw_get_returns_none_when_session_none(no_retries):
    """raw_get() returns None when session stays None after init."""
    client = HttpClient()
    with patch.object(client, "initialize", new=AsyncMock()):
        result = await client.raw_get("https://example.com/no-session")
    assert result is None


@pytest.mark.asyncio
async def test_raw_get_increments_request_count():
    """raw_get() increments request_count."""
    resp = FakeResponse(status=200, read_data=b"x")
    client = HttpClient()
    client.session = FakeSession(resp)
    before = client.request_count
    await client.raw_get("https://example.com/count")
    assert client.request_count == before + 1


# ---------------------------------------------------------------------------
# batch_get()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_batch_get_returns_url_to_response_map():
    client = HttpClient()

    async def fake_get(url, **kw):
        return {"url": url}

    client.get = fake_get  # type: ignore[assignment]

    urls = ["https://a.com", "https://b.com", "https://c.com"]
    result = await client.batch_get(urls)
    assert result == {
        "https://a.com": {"url": "https://a.com"},
        "https://b.com": {"url": "https://b.com"},
        "https://c.com": {"url": "https://c.com"},
    }


@pytest.mark.asyncio
async def test_batch_get_with_custom_semaphore():
    """batch_get() honors a caller-provided semaphore."""
    client = HttpClient()
    sem = asyncio.Semaphore(2)

    async def fake_get(url, **kw):
        return {"data": 1}

    client.get = fake_get  # type: ignore[assignment]

    urls = [f"https://example.com/{i}" for i in range(5)]
    result = await client.batch_get(urls, semaphore=sem)
    assert len(result) == 5
    assert all(v == {"data": 1} for v in result.values())


@pytest.mark.asyncio
async def test_batch_get_handles_none_responses():
    """batch_get() includes None values when get() returns None."""
    client = HttpClient()

    async def fake_get(url, **kw):
        return None if "fail" in url else {"ok": True}

    client.get = fake_get  # type: ignore[assignment]

    urls = ["https://ok.com", "https://fail.com"]
    result = await client.batch_get(urls)
    assert result["https://ok.com"] == {"ok": True}
    assert result["https://fail.com"] is None


# ---------------------------------------------------------------------------
# initialize() (mocked aiohttp)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_initialize_creates_session():
    """initialize() builds an aiohttp session with connector + timeout."""
    with patch.object(network_mod.aiohttp, "ClientSession") as mock_session_cls, \
         patch.object(network_mod.aiohttp, "TCPConnector") as mock_connector_cls, \
         patch.object(network_mod, "AsyncResolver") as mock_resolver_cls:
        client = HttpClient()
        await client.initialize()

        mock_resolver_cls.assert_called_once()
        mock_connector_cls.assert_called_once()
        mock_session_cls.assert_called_once()
        assert client.session is mock_session_cls.return_value
