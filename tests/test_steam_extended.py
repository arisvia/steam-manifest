"""Extended tests for steam_manifest.core.steam.SteamApp.

Covers search_app() (numeric shortcut, fuzzy single/multi-result, interactive
selection, invalid input, KeyboardInterrupt), fetch_app_details() (the actual
method name; task spec called it get_app_details), batch_fetch_dlc_details(),
clear(), and error/exception paths. Network calls are mocked via AsyncMock.
"""

import pytest
from unittest.mock import AsyncMock, patch

from steam_manifest.core.constants import Urls
from steam_manifest.core.steam import SteamApp


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_client(get_return=None, get_side_effect=None, batch_return=None):
    """Build a mock HttpClient with async get/batch_get."""
    client = AsyncMock()
    if get_side_effect is not None:
        client.get.side_effect = get_side_effect
    else:
        client.get.return_value = get_return
    client.batch_get.return_value = batch_return or {}
    return client


# ===========================================================================
# search_app — numeric ID shortcut
# ===========================================================================


async def test_search_app_numeric_id():
    client = make_client()
    steam = SteamApp(client)
    result = await steam.search_app("730")
    assert result == 730
    assert steam.app_id == "730"
    client.get.assert_not_called()


async def test_search_app_numeric_preserves_leading_zeros():
    client = make_client()
    steam = SteamApp(client)
    # "00123".isdigit() is True; int strips leading zeros
    result = await steam.search_app("00123")
    assert result == 123
    assert steam.app_id == "00123"


# ===========================================================================
# search_app — fuzzy search, single result auto-select
# ===========================================================================


async def test_search_app_single_result_auto_select():
    payload = {"items": [{"id": "42", "name": "The Answer", "type": "game"}]}
    client = make_client(get_return=payload)
    steam = SteamApp(client)

    result = await steam.search_app("answer")
    assert result == 42
    assert steam.app_id == "42"
    client.get.assert_awaited_once_with(Urls.steam_search("answer"))


# ===========================================================================
# search_app — multiple results, interactive selection
# ===========================================================================


async def test_search_app_multi_result_valid_choice():
    items = [
        {"id": str(i), "name": f"Game{i}", "type": "game"}
        for i in range(1, 4)
    ]
    client = make_client(get_return={"items": items})
    steam = SteamApp(client)

    with patch("builtins.input", return_value="2"):
        result = await steam.search_app("game")

    assert result == 2
    assert steam.app_id == "2"


async def test_search_app_multi_result_invalid_then_valid():
    items = [
        {"id": "10", "name": "A", "type": "game"},
        {"id": "20", "name": "B", "type": "game"},
    ]
    client = make_client(get_return={"items": items})
    steam = SteamApp(client)

    # First "abc" (ValueError), then "0" (out of range), then "1" (valid)
    with patch("builtins.input", side_effect=["abc", "0", "1"]):
        result = await steam.search_app("x")

    assert result == 10
    assert steam.app_id == "10"


async def test_search_app_multi_result_out_of_range_high():
    items = [{"id": "5", "name": "Only", "type": "game"}]
    client = make_client(get_return={"items": items})
    steam = SteamApp(client)

    with patch("builtins.input", side_effect=["99", "1"]):
        result = await steam.search_app("only")

    assert result == 5


async def test_search_app_multi_result_keyboard_interrupt_then_valid():
    items = [
        {"id": "7", "name": "Seven", "type": "game"},
        {"id": "8", "name": "Eight", "type": "game"},
    ]
    client = make_client(get_return={"items": items})
    steam = SteamApp(client)

    with patch("builtins.input", side_effect=[KeyboardInterrupt(), "1"]):
        result = await steam.search_app("seven")

    assert result == 7


async def test_search_app_multi_result_more_than_ten_truncates():
    items = [
        {"id": str(i), "name": f"G{i}", "type": "game"} for i in range(15)
    ]
    client = make_client(get_return={"items": items})
    steam = SteamApp(client)

    # Choice 10 is valid (index 9); choice 11 would be out of the [:10] slice
    with patch("builtins.input", return_value="10"):
        result = await steam.search_app("g")

    assert result == 9


async def test_search_app_multi_result_item_missing_type_defaults_unknown():
    items = [
        {"id": "1", "name": "NoType"},  # no "type" key
        {"id": "2", "name": "HasType", "type": "dlc"},
    ]
    client = make_client(get_return={"items": items})
    steam = SteamApp(client)

    with patch("builtins.input", return_value="1"):
        result = await steam.search_app("x")

    assert result == 1


# ===========================================================================
# search_app — empty / malformed responses
# ===========================================================================


async def test_search_app_empty_items_list():
    client = make_client(get_return={"items": []})
    steam = SteamApp(client)
    result = await steam.search_app("nonexistent")
    assert result is None


async def test_search_app_missing_items_key():
    client = make_client(get_return={"unexpected": True})
    steam = SteamApp(client)
    result = await steam.search_app("x")
    assert result is None


async def test_search_app_none_response():
    client = make_client(get_return=None)
    steam = SteamApp(client)
    result = await steam.search_app("x")
    assert result is None


# ===========================================================================
# search_app — exception handling
# ===========================================================================


async def test_search_app_api_exception_returns_none():
    client = make_client(get_side_effect=RuntimeError("network down"))
    steam = SteamApp(client)
    result = await steam.search_app("x")
    assert result is None


# ===========================================================================
# fetch_app_details — success cases
# ===========================================================================


async def test_fetch_app_details_success_with_dlc():
    appid = "42"
    url = Urls.steam_app_details(appid)
    payload = {appid: {"success": True, "data": {"name": "Game", "dlc": [1, 2]}}}
    client = make_client(get_return=payload)
    steam = SteamApp(client)

    ok = await steam.fetch_app_details(appid)
    assert ok is True
    assert steam.app_name == "Game"
    assert steam.dlc_ids == [1, 2]
    client.get.assert_awaited_once_with(url)


async def test_fetch_app_details_success_no_dlc():
    appid = "7"
    payload = {appid: {"success": True, "data": {"name": "Solo", "dlc": []}}}
    client = make_client(get_return=payload)
    steam = SteamApp(client)

    ok = await steam.fetch_app_details(appid)
    assert ok is True
    assert steam.app_name == "Solo"
    assert steam.dlc_ids == []


async def test_fetch_app_details_success_missing_dlc_key():
    appid = "9"
    payload = {appid: {"success": True, "data": {"name": "NoDLCField"}}}
    client = make_client(get_return=payload)
    steam = SteamApp(client)

    ok = await steam.fetch_app_details(appid)
    assert ok is True
    assert steam.app_name == "NoDLCField"
    assert steam.dlc_ids == []


async def test_fetch_app_details_success_missing_name():
    appid = "9"
    payload = {appid: {"success": True, "data": {"dlc": [1]}}}
    client = make_client(get_return=payload)
    steam = SteamApp(client)

    ok = await steam.fetch_app_details(appid)
    assert ok is True
    assert steam.app_name is None


# ===========================================================================
# fetch_app_details — error / failure cases
# ===========================================================================


async def test_fetch_app_details_none_response():
    client = make_client(get_return=None)
    steam = SteamApp(client)
    ok = await steam.fetch_app_details("42")
    assert ok is False


async def test_fetch_app_details_non_dict_response():
    client = make_client(get_return="not a dict")
    steam = SteamApp(client)
    ok = await steam.fetch_app_details("42")
    assert ok is False


async def test_fetch_app_details_success_false():
    appid = "42"
    payload = {appid: {"success": False}}
    client = make_client(get_return=payload)
    steam = SteamApp(client)
    ok = await steam.fetch_app_details(appid)
    assert ok is False


async def test_fetch_app_details_missing_appid_key():
    appid = "42"
    payload = {"999": {"success": True, "data": {"name": "Other"}}}
    client = make_client(get_return=payload)
    steam = SteamApp(client)
    ok = await steam.fetch_app_details(appid)
    # app_data = result.get(app_id, {}) → {} → success falsy → False
    assert ok is False


async def test_fetch_app_details_exception_returns_false():
    client = make_client(get_side_effect=ConnectionError("timeout"))
    steam = SteamApp(client)
    ok = await steam.fetch_app_details("42")
    assert ok is False


# ===========================================================================
# batch_fetch_dlc_details
# ===========================================================================


async def test_batch_fetch_dlc_details_empty_list():
    client = make_client()
    steam = SteamApp(client)
    result = await steam.batch_fetch_dlc_details([])
    assert result == {}
    client.batch_get.assert_not_called()


async def test_batch_fetch_dlc_details_success():
    dlc_ids = [101, 102]
    urls = [Urls.steam_app_details(str(d)) for d in dlc_ids]
    batch_return = {
        urls[0]: {"101": {"success": True, "data": {"name": "DLC One"}}},
        urls[1]: {"102": {"success": True, "data": {"name": "DLC Two"}}},
    }
    client = make_client(batch_return=batch_return)
    steam = SteamApp(client)

    result = await steam.batch_fetch_dlc_details(dlc_ids)
    assert result == {101: "DLC One", 102: "DLC Two"}
    client.batch_get.assert_awaited_once_with(urls)


async def test_batch_fetch_dlc_details_partial_failure():
    dlc_ids = [101, 102]
    urls = [Urls.steam_app_details(str(d)) for d in dlc_ids]
    batch_return = {
        urls[0]: {"101": {"success": True, "data": {"name": "OK"}}},
        urls[1]: {"102": {"success": False}},  # failed DLC
    }
    client = make_client(batch_return=batch_return)
    steam = SteamApp(client)

    result = await steam.batch_fetch_dlc_details(dlc_ids)
    assert result == {101: "OK"}


async def test_batch_fetch_dlc_details_none_data_skipped():
    dlc_ids = [101, 102]
    urls = [Urls.steam_app_details(str(d)) for d in dlc_ids]
    batch_return = {
        urls[0]: None,
        urls[1]: "garbage",
    }
    client = make_client(batch_return=batch_return)
    steam = SteamApp(client)

    result = await steam.batch_fetch_dlc_details(dlc_ids)
    assert result == {}


async def test_batch_fetch_dlc_details_missing_name_defaults_unknown():
    dlc_ids = [101]
    urls = [Urls.steam_app_details(str(d)) for d in dlc_ids]
    batch_return = {
        urls[0]: {"101": {"success": True, "data": {}}},  # no "name"
    }
    client = make_client(batch_return=batch_return)
    steam = SteamApp(client)

    result = await steam.batch_fetch_dlc_details(dlc_ids)
    assert result == {101: "Unknown"}


# ===========================================================================
# clear
# ===========================================================================


async def test_clear_resets_state():
    client = make_client()
    steam = SteamApp(client)
    steam.app_id = "42"
    steam.app_name = "Game"
    steam.dlc_ids = [1, 2, 3]

    steam.clear()

    assert steam.app_id == ""
    assert steam.app_name is None
    assert steam.dlc_ids == []


def test_clear_on_fresh_instance():
    client = make_client()
    steam = SteamApp(client)
    steam.clear()
    assert steam.app_id == ""
    assert steam.app_name is None
    assert steam.dlc_ids == []
