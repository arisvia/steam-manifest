"""
Tests for CLI module.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from steam_manifest.cli import init_command_args, main, show_banner


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


def test_init_command_args_with_log_options():
    """Test CLI argument parsing with log options."""
    with patch(
        "sys.argv",
        ["steam-manifest", "-a", "480", "--log-level", "DEBUG", "--log-dir", "/tmp/logs"],
    ):
        args = init_command_args()
        assert args.appid == "480"
        assert args.log_level == "DEBUG"
        assert args.log_dir == Path("/tmp/logs")


def test_init_command_args_with_no_log():
    """Test CLI argument parsing with --no-log flag."""
    with patch("sys.argv", ["steam-manifest", "-a", "480", "--no-log"]):
        args = init_command_args()
        assert args.appid == "480"
        assert args.no_log is True


def test_setup_logger_debug_mode():
    """Test logger setup in debug mode."""
    from steam_manifest.core.loghelper import setup_logger
    
    with patch("steam_manifest.core.loghelper.logger") as mock_logger:
        setup_logger(log_level="DEBUG")
        mock_logger.remove.assert_called_once()
        # Should add both console and file handlers
        assert mock_logger.add.call_count == 2


def test_setup_logger_info_mode():
    """Test logger setup in info mode."""
    from steam_manifest.core.loghelper import setup_logger
    
    with patch("steam_manifest.core.loghelper.logger") as mock_logger:
        setup_logger(log_level="INFO")
        mock_logger.remove.assert_called_once()
        # Should add both console and file handlers
        assert mock_logger.add.call_count == 2


def test_setup_logger_no_console():
    """Test logger setup with console disabled."""
    from steam_manifest.core.loghelper import setup_logger
    
    with patch("steam_manifest.core.loghelper.logger") as mock_logger:
        setup_logger(log_level="INFO", console_enable=False)
        mock_logger.remove.assert_called_once()
        # Should only add file handler
        assert mock_logger.add.call_count == 1


def test_setup_logger_no_file():
    """Test logger setup with file disabled."""
    from steam_manifest.core.loghelper import setup_logger
    
    with patch("steam_manifest.core.loghelper.logger") as mock_logger:
        setup_logger(log_level="INFO", file_enable=False)
        mock_logger.remove.assert_called_once()
        # Should only add console handler
        assert mock_logger.add.call_count == 1


def test_setup_logger_both_disabled():
    """Test logger setup with both console and file disabled."""
    from steam_manifest.core.loghelper import setup_logger
    
    with patch("steam_manifest.core.loghelper.logger") as mock_logger:
        setup_logger(log_level="INFO", console_enable=False, file_enable=False)
        mock_logger.remove.assert_called_once()
        # Should not add any handlers
        mock_logger.add.assert_not_called()


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
