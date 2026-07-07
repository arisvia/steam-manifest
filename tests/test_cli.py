"""
Tests for CLI module.
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from steam_manifest.cli import init_command_args, init_logger, main, show_banner


def test_init_command_args_with_appid():
    """Test CLI argument parsing with appid."""
    with patch("sys.argv", ["steam-manifest", "-a", "480"]):
        args = init_command_args()
        assert args.appid == "480"
        assert args.debug is False
        assert args.fixed is False


def test_init_command_args_with_debug():
    """Test CLI argument parsing with debug flag."""
    with patch("sys.argv", ["steam-manifest", "-a", "480", "-d"]):
        args = init_command_args()
        assert args.appid == "480"
        assert args.debug is True


def test_init_command_args_with_all_options():
    """Test CLI argument parsing with all options."""
    with patch(
        "sys.argv",
        ["steam-manifest", "-a", "480", "-k", "token123", "-r", "custom/repo", "-f", "-d"],
    ):
        args = init_command_args()
        assert args.appid == "480"
        assert args.key == "token123"
        assert args.repo == "custom/repo"
        assert args.fixed is True
        assert args.debug is True


def test_init_logger_debug_mode():
    """Test logger initialization in debug mode."""
    with patch("steam_manifest.cli.logger") as mock_logger:
        init_logger(debug=True)
        mock_logger.remove.assert_called_once()
        mock_logger.add.assert_called_once()
        # Check that DEBUG level was set
        call_args = mock_logger.add.call_args
        assert call_args[1]["level"] == "DEBUG"


def test_init_logger_info_mode():
    """Test logger initialization in info mode."""
    with patch("steam_manifest.cli.logger") as mock_logger:
        init_logger(debug=False)
        mock_logger.remove.assert_called_once()
        mock_logger.add.assert_called_once()
        # Check that INFO level was set
        call_args = mock_logger.add.call_args
        assert call_args[1]["level"] == "INFO"


def test_show_banner(capsys):
    """Test banner display."""
    show_banner()
    # Just verify it doesn't crash - output is captured by rich
    # and may not appear in capsys


@pytest.mark.asyncio
async def test_main_with_valid_workflow():
    """Test main workflow with mocked dependencies."""
    with patch("sys.argv", ["steam-manifest", "-a", "480"]), \
         patch("steam_manifest.cli.verify_steam_path") as mock_verify, \
         patch("steam_manifest.cli.HttpClient") as mock_client_class, \
         patch("steam_manifest.cli.ManifestStorage") as mock_storage_class, \
         patch("steam_manifest.cli.SteamApp") as mock_steam_class, \
         patch("steam_manifest.cli.GitHubRepo") as mock_github_class:

        # Setup mocks
        mock_verify.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        mock_storage = MagicMock()
        mock_storage.save_lua_config = AsyncMock(return_value=True)
        mock_storage_class.return_value = mock_storage

        mock_steam = MagicMock()
        mock_steam.search_app = AsyncMock(return_value=480)
        mock_steam.fetch_app_details = AsyncMock(return_value=None)
        mock_steam.app_name = "Test Game"
        mock_steam.dlc_ids = []
        mock_steam_class.return_value = mock_steam

        mock_github = MagicMock()
        mock_github.check_rate_limit = AsyncMock(return_value=True)
        mock_github.find_repository = AsyncMock(return_value="test/repo")
        mock_github.fetch_repository_files = AsyncMock(return_value=[])
        mock_github_class.return_value = mock_github

        # Test async_main directly to avoid asyncio.run() nesting
        from steam_manifest.cli import async_main
        await async_main()


def test_main_keyboard_interrupt():
    """Test main handles keyboard interrupt gracefully."""
    with patch("sys.argv", ["steam-manifest", "-a", "480"]), \
         patch("steam_manifest.cli.asyncio.run", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
