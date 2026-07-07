"""Extended tests for steam_manifest.core.github.GitHubRepo.

Covers find_repository(), fetch_repository_files(), process_files(), and API
rate-limit handling (check_rate_limit) using pytest + unittest.mock + AsyncMock.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import steam_manifest.core.github as github_mod
from steam_manifest.core.constants import DEFAULT_REPOS, Urls
from steam_manifest.core.github import GitHubRepo
from steam_manifest.core.storage import ManifestStorage


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
def make_branch_data(date="2023-01-01T00:00:00Z", tree_url="tree_url"):
    return {"commit": {"commit": {"committer": {"date": date}, "tree": {"url": tree_url}}}}


class DummyProgress:
    """Stand-in for rich.Progress that captures task progression."""

    def __init__(self, *a, **k):
        self.advances = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_task(self, *a, **k):
        return 1

    def advance(self, *a, **k):
        self.advances += 1


@pytest.fixture
def patch_progress(monkeypatch):
    monkeypatch.setattr(github_mod, "Progress", DummyProgress)


@pytest.fixture
def storage():
    s = ManifestStorage()
    # Replace blocking storage methods with AsyncMocks.
    s.save_manifest_file = AsyncMock(return_value=True)  # type: ignore[assignment]
    s.parse_app_info = AsyncMock(return_value="AppName")  # type: ignore[assignment]
    s.parse_depot_key = AsyncMock(return_value=True)  # type: ignore[assignment]
    s.parse_config_json = AsyncMock(return_value=([], []))  # type: ignore[assignment]
    return s


@pytest.fixture
def client():
    """A MagicMock api_client whose .get/.raw_get are AsyncMocks."""
    c = MagicMock()
    c.get = AsyncMock()
    c.raw_get = AsyncMock()
    c.request_count = 0
    c.cache_hits = 0
    c.cache = {}
    return c


@pytest.fixture
def gh(client, storage):
    return GitHubRepo(client, storage)


# ---------------------------------------------------------------------------
# check_rate_limit()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_check_rate_limit_ok(gh, client):
    client.get.return_value = {"rate": {"remaining": 50, "reset": 1700000000}}
    ok = await gh.check_rate_limit()
    assert ok is True
    assert gh.rate_limit_info["remaining"] == 50
    client.get.assert_awaited_once_with(Urls.GITHUB_RATE_LIMIT)


@pytest.mark.asyncio
async def test_check_rate_limit_zero_blocks(gh, client):
    client.get.return_value = {"rate": {"remaining": 0, "reset": 1700000000}}
    ok = await gh.check_rate_limit()
    assert ok is False
    assert "reset_time" in gh.rate_limit_info


@pytest.mark.asyncio
async def test_check_rate_limit_missing_rate_allows(gh, client):
    """If API returns no 'rate' key, we proceed optimistically."""
    client.get.return_value = {}
    ok = await gh.check_rate_limit()
    assert ok is True


@pytest.mark.asyncio
async def test_check_rate_limit_none_response_allows(gh, client):
    client.get.return_value = None
    ok = await gh.check_rate_limit()
    assert ok is True


@pytest.mark.asyncio
async def test_check_rate_limit_exception_allows(gh, client):
    """On exception, default to allow (return True)."""
    client.get.side_effect = RuntimeError("boom")
    ok = await gh.check_rate_limit()
    assert ok is True


# ---------------------------------------------------------------------------
# find_repository()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_find_repository_picks_latest_date(gh, client):
    async def fake_get(url):
        if "repo1" in url:
            return make_branch_data(date="2020-01-01T00:00:00Z")
        if "repo2" in url:
            return make_branch_data(date="2024-01-01T00:00:00Z")
        return None

    client.get.side_effect = fake_get

    chosen = await gh.find_repository("123", custom_repos=["repo1", "repo2"])
    assert chosen == "repo2"
    assert gh.current_repo == "repo2"


@pytest.mark.asyncio
async def test_find_repository_none_when_no_branches(gh, client):
    client.get.return_value = None
    chosen = await gh.find_repository("123", custom_repos=["a/b", "c/d"])
    assert chosen is None
    assert gh.current_repo is None


@pytest.mark.asyncio
async def test_find_repository_uses_default_repos(gh, client):
    """Without custom_repos, uses DEFAULT_REPOS."""
    client.get.return_value = None  # no branches found
    await gh.find_repository("123")
    # Should have queried each default repo exactly once.
    assert client.get.await_count == len(DEFAULT_REPOS)


@pytest.mark.asyncio
async def test_find_repository_handles_exception_in_one_repo(gh, client):
    """An exception from one repo's _check_repo_branch should not break others."""
    call = {"n": 0}

    async def fake_get(url):
        call["n"] += 1
        if call["n"] == 1:
            raise RuntimeError("network error")
        return make_branch_data(date="2023-06-01T00:00:00Z")

    client.get.side_effect = fake_get

    chosen = await gh.find_repository("123", custom_repos=["err/repo", "ok/repo"])
    assert chosen == "ok/repo"


@pytest.mark.asyncio
async def test_find_repository_single_repo_found(gh, client):
    client.get.return_value = make_branch_data(date="2023-05-01T00:00:00Z")
    chosen = await gh.find_repository("456", custom_repos=["only/repo"])
    assert chosen == "only/repo"


@pytest.mark.asyncio
async def test_find_repository_missing_commit_returns_none(gh, client):
    """Response without 'commit' key is treated as no branch."""
    client.get.return_value = {"some": "other"}
    chosen = await gh.find_repository("789", custom_repos=["x/y"])
    assert chosen is None


# ---------------------------------------------------------------------------
# fetch_repository_files()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fetch_repository_files_success(gh, client):
    branch_data = make_branch_data(tree_url="https://api/tree_url")
    tree_data = {"tree": [
        {"path": "a.manifest", "type": "blob"},
        {"path": "key.vdf", "type": "blob"},
    ]}

    async def fake_get(url):
        if "branches" in url:
            return branch_data
        return tree_data

    client.get.side_effect = fake_get

    files = await gh.fetch_repository_files("repo", "branch")
    assert files is not None
    assert len(files) == 2
    assert files[0]["path"] == "a.manifest"


@pytest.mark.asyncio
async def test_fetch_repository_files_no_branch_data(gh, client):
    client.get.return_value = None
    files = await gh.fetch_repository_files("repo", "branch")
    assert files is None


@pytest.mark.asyncio
async def test_fetch_repository_files_missing_commit(gh, client):
    """branch_data without 'commit' returns None."""
    client.get.return_value = {"foo": "bar"}
    files = await gh.fetch_repository_files("repo", "branch")
    assert files is None


@pytest.mark.asyncio
async def test_fetch_repository_files_no_tree_data(gh, client):
    async def fake_get(url):
        if "branches" in url:
            return make_branch_data()
        return None  # tree fetch returns None

    client.get.side_effect = fake_get
    files = await gh.fetch_repository_files("repo", "branch")
    assert files is None


@pytest.mark.asyncio
async def test_fetch_repository_files_missing_tree_key(gh, client):
    async def fake_get(url):
        if "branches" in url:
            return make_branch_data()
        return {"sha": "abc"}  # no 'tree' key

    client.get.side_effect = fake_get
    files = await gh.fetch_repository_files("repo", "branch")
    assert files is None


@pytest.mark.asyncio
async def test_fetch_repository_files_exception_returns_none(gh, client):
    client.get.side_effect = RuntimeError("boom")
    files = await gh.fetch_repository_files("repo", "branch")
    assert files is None


# ---------------------------------------------------------------------------
# process_files()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_files_all_success(gh, client, storage, patch_progress, tmp_path):
    client.raw_get.return_value = b"content"

    files = [
        {"path": "480_abc.manifest", "type": "blob"},
        {"path": "appinfo.vdf", "type": "blob"},
        {"path": "key.vdf", "type": "blob"},
        {"path": "config.json", "type": "blob"},
    ]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is True
    storage.save_manifest_file.assert_awaited()
    storage.parse_app_info.assert_awaited_once()
    storage.parse_depot_key.assert_awaited_once()
    storage.parse_config_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_files_skips_directories(gh, client, storage, patch_progress, tmp_path):
    """Tree-type entries are skipped (return True) without network calls."""
    client.raw_get.return_value = b"x"
    files = [{"path": "somedir", "type": "tree"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is True
    client.raw_get.assert_not_awaited()
    storage.save_manifest_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_files_unknown_type_is_skipped(gh, client, storage, patch_progress, tmp_path):
    """Files that don't match manifest/vdf/config are ignored as success."""
    files = [{"path": "readme.md", "type": "blob"}]
    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is True
    client.raw_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_files_manifest_download_failure(gh, client, storage, patch_progress, tmp_path):
    """When raw_get returns None for a manifest, process_files reports failure."""
    client.raw_get.return_value = None
    files = [{"path": "480_abc.manifest", "type": "blob"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is False
    storage.save_manifest_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_files_save_manifest_failure(gh, client, storage, patch_progress, tmp_path):
    """When storage.save_manifest_file returns False, process_files reports failure."""
    client.raw_get.return_value = b"data"
    storage.save_manifest_file.return_value = False
    files = [{"path": "480_abc.manifest", "type": "blob"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_process_files_vdf_appinfo_success(gh, client, storage, patch_progress, tmp_path):
    client.raw_get.return_value = b"vdf-content"
    files = [{"path": "appinfo.vdf", "type": "blob"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is True
    storage.parse_app_info.assert_awaited_once_with(b"vdf-content")


@pytest.mark.asyncio
async def test_process_files_vdf_key_success(gh, client, storage, patch_progress, tmp_path):
    client.raw_get.return_value = b"keys"
    files = [{"path": "key.vdf", "type": "blob"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is True
    storage.parse_depot_key.assert_awaited_once_with(b"keys")


@pytest.mark.asyncio
async def test_process_files_config_success(gh, client, storage, patch_progress, tmp_path):
    client.get.return_value = {"dlcs": [1, 2], "packagedlcs": [3]}
    files = [{"path": "config.json", "type": "blob"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is True
    storage.parse_config_json.assert_awaited_once_with({"dlcs": [1, 2], "packagedlcs": [3]})


@pytest.mark.asyncio
async def test_process_files_config_none_returns_failure(gh, client, storage, patch_progress, tmp_path):
    """When api_client.get returns None for config.json, _handle_config returns False."""
    client.get.return_value = None
    files = [{"path": "config.json", "type": "blob"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_process_files_empty_list(gh, client, storage, patch_progress, tmp_path):
    ok = await gh.process_files("repo", "branch", [], tmp_path)
    assert ok is True


@pytest.mark.asyncio
async def test_process_files_exception_in_single_file(gh, client, storage, patch_progress, tmp_path):
    """An exception inside _process_single_file is caught -> False, overall fails."""
    client.raw_get.side_effect = RuntimeError("download error")
    files = [{"path": "480_abc.manifest", "type": "blob"}]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_process_files_with_custom_semaphore(gh, client, storage, patch_progress, tmp_path):
    """A caller-provided semaphore is used instead of creating a default."""
    client.raw_get.return_value = b"data"
    sem = asyncio.Semaphore(1)
    files = [
        {"path": "480_abc.manifest", "type": "blob"},
        {"path": "481_def.manifest", "type": "blob"},
    ]

    ok = await gh.process_files("repo", "branch", files, tmp_path, semaphore=sem)
    assert ok is True
    assert client.raw_get.await_count == 2


@pytest.mark.asyncio
async def test_process_files_partial_failure(gh, client, storage, patch_progress, tmp_path):
    """One failing file + one succeeding -> overall returns False."""
    call = {"n": 0}

    async def fake_raw_get(url):
        call["n"] += 1
        return None if call["n"] == 1 else b"data"

    client.raw_get.side_effect = fake_raw_get
    files = [
        {"path": "480_fail.manifest", "type": "blob"},
        {"path": "481_ok.manifest", "type": "blob"},
    ]

    ok = await gh.process_files("repo", "branch", files, tmp_path)
    assert ok is False


# ---------------------------------------------------------------------------
# _handle_manifest / _handle_vdf / _handle_config internals
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_manifest_empty_content_returns_false(gh, client, storage, tmp_path):
    client.raw_get.return_value = None
    result = await gh._handle_manifest("repo", "branch", "480_x.manifest", tmp_path)
    assert result is False


@pytest.mark.asyncio
async def test_handle_vdf_unknown_path_returns_true(gh, client, storage):
    """VDF paths other than appinfo.vdf/key.vdf are ignored as success."""
    client.raw_get.return_value = b"data"
    result = await gh._handle_vdf("repo", "branch", "unknown.vdf")
    assert result is True


@pytest.mark.asyncio
async def test_handle_vdf_empty_content_returns_false(gh, client, storage):
    client.raw_get.return_value = None
    result = await gh._handle_vdf("repo", "branch", "appinfo.vdf")
    assert result is False


@pytest.mark.asyncio
async def test_handle_config_empty_data_returns_false(gh, client, storage):
    client.get.return_value = None
    result = await gh._handle_config("repo", "branch", "config.json")
    assert result is False


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------
def test_clear_resets_state(gh):
    gh.current_repo = "some/repo"
    gh.rate_limit_info = {"remaining": 5}
    gh.clear()
    assert gh.current_repo is None
    assert gh.rate_limit_info == {}
