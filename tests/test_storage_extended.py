"""Extended tests for steam_manifest.core.storage.ManifestStorage.

Covers: save_manifest_file (saves manifest files), save_lua_config (Lua config
generation), filesystem ops (mkdir/write), and error handling (permission,
disk-full analogues via mocked exceptions).

Note: storage.py exposes no save_manifests() (plural) nor save_json_config();
the actual write paths are save_manifest_file() and save_lua_config(). Tests
target the real API.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from steam_manifest.core.constants import Steam
from steam_manifest.core.storage import ManifestStorage

# ---------------------------------------------------------------------------
# save_manifest_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_manifest_file_writes_to_depotcache(tmp_path):
    storage = ManifestStorage()
    path = "123456_abcef.manifest"
    content = b"\x00\x01manifest-bytes"

    ok = await storage.save_manifest_file(path, tmp_path, content)

    assert ok is True
    saved = tmp_path / Steam.DEPOT_CACHE / path
    assert saved.read_bytes() == content
    assert path in storage.manifests


@pytest.mark.asyncio
async def test_save_manifest_file_skips_existing(tmp_path):
    storage = ManifestStorage()
    path = "111_abc.manifest"
    target = tmp_path / Steam.DEPOT_CACHE / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"original")

    ok = await storage.save_manifest_file(path, tmp_path, b"new")

    assert ok is True
    # 内容未被覆盖
    assert target.read_bytes() == b"original"
    # 已存在时不会加入 manifests 列表
    assert path not in storage.manifests


@pytest.mark.asyncio
async def test_save_manifest_file_creates_nested_dirs(tmp_path):
    storage = ManifestStorage()
    # 带子目录的相对路径
    path = "sub/deep/222_key.manifest"
    content = b"x"

    ok = await storage.save_manifest_file(path, tmp_path, content)

    assert ok is True
    assert (tmp_path / Steam.DEPOT_CACHE / path).read_bytes() == b"x"


@pytest.mark.asyncio
async def test_save_manifest_file_atomic_no_tmp_leftover(tmp_path):
    storage = ManifestStorage()
    path = "333_xyz.manifest"
    await storage.save_manifest_file(path, tmp_path, b"data")

    # 原子写：.tmp 应已被 replace 移走
    tmp = tmp_path / Steam.DEPOT_CACHE / "333_xyz.tmp"
    assert not tmp.exists()


@pytest.mark.asyncio
async def test_save_manifest_file_returns_false_on_write_error(tmp_path):
    storage = ManifestStorage()
    path = "444_err.manifest"

    with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
        ok = await storage.save_manifest_file(path, tmp_path, b"x")

    assert ok is False
    assert path not in storage.manifests


@pytest.mark.asyncio
async def test_save_manifest_file_returns_false_on_mkdir_error(tmp_path):
    storage = ManifestStorage()
    path = "555_perm.manifest"

    with patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
        ok = await storage.save_manifest_file(path, tmp_path, b"x")

    assert ok is False


# ---------------------------------------------------------------------------
# save_lua_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_lua_config_basic(tmp_path):
    storage = ManifestStorage()
    storage.depots = {100: "keyA", 200: None}

    ok = await storage.save_lua_config("123456", "MyGame", tmp_path)

    assert ok is True
    lua_file = tmp_path / Steam.PLUGIN_DIR / "123456.lua"
    text = lua_file.read_text(encoding="utf-8")

    assert "-- MyGame" in text
    assert 'addappid(100, 1, "keyA")' in text
    assert "addappid(200, 1)" in text


@pytest.mark.asyncio
async def test_save_lua_config_sorted_depots(tmp_path):
    storage = ManifestStorage()
    storage.depots = {300: "c", 100: "a", 200: "b"}

    await storage.save_lua_config("app", None, tmp_path)

    text = (tmp_path / Steam.PLUGIN_DIR / "app.lua").read_text(encoding="utf-8")
    # 排序：100 在 200 前，200 在 300 前
    assert (
        text.index("addappid(100")
        < text.index("addappid(200")
        < text.index("addappid(300")
    )


@pytest.mark.asyncio
async def test_save_lua_config_no_app_name(tmp_path):
    storage = ManifestStorage()
    storage.depots = {10: "k"}

    await storage.save_lua_config("99", None, tmp_path)

    text = (tmp_path / Steam.PLUGIN_DIR / "99.lua").read_text(encoding="utf-8")
    assert not text.startswith("--")
    assert 'addappid(10, 1, "k")' in text


@pytest.mark.asyncio
async def test_save_lua_config_fixed_manifest(tmp_path):
    storage = ManifestStorage()
    storage.depots = {100: "keyA"}
    storage.manifests = ["100_abcdef123456.manifest", "200_deadbeef7890.manifest"]

    ok = await storage.save_lua_config(
        "123456", "Game", tmp_path, use_fixed_manifest=True
    )

    assert ok is True
    text = (tmp_path / Steam.PLUGIN_DIR / "123456.lua").read_text(encoding="utf-8")
    assert 'setManifestid(100, "abcdef123456")' in text
    assert 'setManifestid(200, "deadbeef7890")' in text


@pytest.mark.asyncio
async def test_save_lua_config_fixed_manifest_skipped_when_empty(tmp_path):
    storage = ManifestStorage()
    storage.depots = {100: "k"}
    # manifests 为空，不应生成 setManifestid
    await storage.save_lua_config("1", "G", tmp_path, use_fixed_manifest=True)

    text = (tmp_path / Steam.PLUGIN_DIR / "1.lua").read_text(encoding="utf-8")
    assert "setManifestid" not in text


@pytest.mark.asyncio
async def test_save_lua_config_creates_plugin_dir(tmp_path):
    storage = ManifestStorage()
    plugin_dir = tmp_path / Steam.PLUGIN_DIR
    assert not plugin_dir.exists()

    await storage.save_lua_config("7", None, tmp_path)

    assert plugin_dir.is_dir()
    assert (plugin_dir / "7.lua").exists()


@pytest.mark.asyncio
async def test_save_lua_config_atomic_no_tmp_leftover(tmp_path):
    storage = ManifestStorage()
    await storage.save_lua_config("8", None, tmp_path)

    assert not (tmp_path / Steam.PLUGIN_DIR / "8.tmp").exists()


@pytest.mark.asyncio
async def test_save_lua_config_returns_false_on_write_error(tmp_path):
    storage = ManifestStorage()
    storage.depots = {1: "k"}

    with patch.object(Path, "write_text", side_effect=OSError("io error")):
        ok = await storage.save_lua_config("9", None, tmp_path)

    assert ok is False


@pytest.mark.asyncio
async def test_save_lua_config_returns_false_on_mkdir_error(tmp_path):
    storage = ManifestStorage()

    with patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
        ok = await storage.save_lua_config("10", None, tmp_path)

    assert ok is False


# ---------------------------------------------------------------------------
# _parse_manifest_ids
# ---------------------------------------------------------------------------


def test_parse_manifest_ids_basic():
    storage = ManifestStorage()
    storage.manifests = ["100_abc123.manifest", "200_def456.manifest"]
    m = storage._parse_manifest_ids()
    assert m == {100: "abc123", 200: "def456"}


def test_parse_manifest_ids_ignores_invalid():
    storage = ManifestStorage()
    storage.manifests = ["notanumber_abc.manifest", "100_xyz.manifest", "garbage"]
    m = storage._parse_manifest_ids()
    assert m == {100: "xyz"}


def test_parse_manifest_ids_empty():
    storage = ManifestStorage()
    assert storage._parse_manifest_ids() == {}


# ---------------------------------------------------------------------------
# 文件系统操作 & 错误处理 - 辅助方法
# ---------------------------------------------------------------------------


def test_add_depot_new():
    storage = ManifestStorage()
    storage.add_depot(500, "key")
    assert storage.depots[500] == "key"


def test_add_depot_does_not_overwrite_existing_key():
    storage = ManifestStorage()
    storage.add_depot(500, "first")
    storage.add_depot(500, "second")  # 已有非空 key，不覆盖
    assert storage.depots[500] == "first"


def test_add_depot_upgrades_none_to_key():
    storage = ManifestStorage()
    storage.add_depot(500, None)
    storage.add_depot(500, "realkey")  # 原为 None，应升级
    assert storage.depots[500] == "realkey"


def test_add_depot_none_does_not_overwrite_key():
    storage = ManifestStorage()
    storage.add_depot(500, "key")
    storage.add_depot(500, None)
    assert storage.depots[500] == "key"


def test_get_depot_list_sorted():
    storage = ManifestStorage()
    storage.depots = {3: "c", 1: "a", 2: None}
    assert storage.get_depot_list() == [(1, "a"), (2, None), (3, "c")]


def test_clear_resets_state():
    storage = ManifestStorage()
    storage.depots = {1: "k"}
    storage.manifests = ["1_x.manifest"]
    storage.clear()
    assert storage.depots == {}
    assert storage.manifests == []


# ---------------------------------------------------------------------------
# parse_config_json (JSON 配置解析路径 - 补 save_json_config 缺失)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_config_json_extracts_dlcs():
    storage = ManifestStorage()
    dlcs, packagedlcs = await storage.parse_config_json(
        {"dlcs": [101, 102], "packagedlcs": [201]}
    )
    assert dlcs == [101, 102]
    assert packagedlcs == [201]
    # dlc id 应作为 None key 加入 depots
    assert storage.depots[101] is None
    assert storage.depots[102] is None


@pytest.mark.asyncio
async def test_parse_config_json_empty():
    storage = ManifestStorage()
    dlcs, packagedlcs = await storage.parse_config_json({})
    assert dlcs == []
    assert packagedlcs == []


@pytest.mark.asyncio
async def test_parse_config_json_error_returns_empty():
    storage = ManifestStorage()
    # 传入不可 .get 的对象触发异常
    dlcs, packagedlcs = await storage.parse_config_json(None)  # type: ignore[arg-type]
    assert dlcs == []
    assert packagedlcs == []


# ---------------------------------------------------------------------------
# save_lua_config 内容完整性 - 一次性写入校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_lua_config_full_content_snapshot(tmp_path):
    storage = ManifestStorage()
    storage.depots = {100: "KEY1", 200: None}
    storage.manifests = ["100_aabbcc.manifest"]

    await storage.save_lua_config("999", "TestApp", tmp_path, use_fixed_manifest=True)

    text = (tmp_path / Steam.PLUGIN_DIR / "999.lua").read_text(encoding="utf-8")
    expected = (
        "-- TestApp\n"
        'addappid(100, 1, "KEY1")\n'
        "addappid(200, 1)\n"
        'setManifestid(100, "aabbcc")\n'
    )
    assert text == expected


# ---------------------------------------------------------------------------
# 并发安全 - save_manifest_file 多次并发调用
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_manifest_file_concurrent_writes(tmp_path):
    storage = ManifestStorage()
    paths = [f"{i}_{i:06x}.manifest" for i in range(20)]
    contents = [f"content-{i}".encode() for i in range(20)]

    await asyncio.gather(
        *[
            storage.save_manifest_file(p, tmp_path, c)
            for p, c in zip(paths, contents, strict=False)
        ]
    )

    for p, c in zip(paths, contents, strict=False):
        assert (tmp_path / Steam.DEPOT_CACHE / p).read_bytes() == c
    assert len(storage.manifests) == 20
