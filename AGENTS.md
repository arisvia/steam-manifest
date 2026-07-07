# AI Agent Project Guide for Steam Manifest Tool

This document provides essential context for AI agents working on the Steam Manifest Tool codebase.

## 🏗️ Architecture Overview

This is an asynchronous Python CLI tool for retrieving Steam manifest files from GitHub repositories.

### Key Components

- **`src/steam_manifest/cli.py`**: Entry point for application logic. Orchestrates the workflow: Steam verification ->
  App lookup ->
  Manifest search -> Download.
    - The CLI entry point is `src.steam_manifest.cli:main` and a console script `steam-manifest` is
      defined in `pyproject.toml` under [project.scripts]. There is no top-level `entry_point.py` shim.
    - Platform notes: on Windows the CLI auto-detects the Steam path via the registry (`winreg`);
      on non-Windows platforms `verify_steam_path()` returns None and the tool will exit if a Steam
      path is not provided.
- **`src/steam_manifest/core/network.py`**: Centralized async HTTP client (`HttpClient`).
    - **Pattern**: Wraps `aiohttp` with `tenacity` for retries, `cachetools` for caching, and `orjson` for fast JSON
      parsing.
    - **Usage**: Use `HttpClient` instance for all network requests.
- **`src/steam_manifest/core/steam.py`**: Manages Steam app identity and store data (`SteamApp`).
    - Resolves App ID/Name and DLC information via Steam Web API.
- **`src/steam_manifest/core/github.py`**: Handles GitHub interactions (`GitHubRepo`).
    - Searches repositories for manifest files and depot keys.
    - Manages rate limits and repository traversal.
- **`src/steam_manifest/core/storage.py`**: Handles file I/O and parsing (`ManifestStorage`).
    - **Pattern**: Offloads CPU-bound VDF/JSON parsing to thread pool executor to avoid blocking the event loop.
    - **Key Libs**: `vdf` (Valve Data Format), `orjson`, `aiofiles`.
- **`src/steam_manifest/core/constants.py`**: Centralized configuration (`Urls`, `Files`, `Steam` classes) and
  constants.

## 🔄 Critical Workflows & Patterns

### Asynchronous Design

- **Core Principle**: The entire application is `async/await` based.
- **Concurrency**: `asyncio` is used extensively. IO-bound tasks run concurrently where possible.
- **CPU-Bound Tasks**: Must be offloaded to an executor:
  ```python
  # Example from src/steam_manifest/core/storage.py
  loop = asyncio.get_event_loop()
  data = await loop.run_in_executor(None, vdf.loads, content.decode())
  ```

### Dependency Injection

- **Service Pattern**: Components (`SteamApp`, `GitHubRepo`, `ManifestStorage`) are instantiated in `cli.main()` and
  injected where needed.
- `HttpClient` is managed as an async context manager and passed to components.

### Error Handling & Logging

- **Logging**: Uses `loguru`.
    - Format: `<green>{time}</green> | <level>{level}</level> | <level>{message}</level>`
    - Usage: `logger.info()`, `logger.error()`, etc.
- **UI Output**: Uses `rich` for user-facing output (tables, progress bars).

## 🛠️ Development & Debugging

### Setup

- **Dependencies**: `pip install -e .`
- **Structure**:
    - `src/steam_manifest`: Flat package structure.
    - `cli.py`, `network.py`, `steam.py`, `github.py`, `storage.py`.

- **Entry point**: The console script `steam-manifest` is declared in `pyproject.toml` and maps to
  `steam_manifest.cli:main`. Use the console script or `python -m steam_manifest.cli` to run the CLI.

- **Version management**: Version is automatically read from `pyproject.toml` via `importlib.metadata`. Only update version in one place.

### Running

```powershell
# Run via installed console script (recommended after `pip install -e .`)
steam-manifest -a <APP_ID_OR_NAME>

# Or run the module directly (no install required)
python -m steam_manifest.cli -a <APP_ID_OR_NAME>

# With Debug logging
steam-manifest -a <APP_ID> -d
python -m steam_manifest.cli -a <APP_ID> -d
```

### Common Tasks

- **Adding a new repository**: Update `DEFAULT_REPOS` in `src/steam_manifest/core/constants.py`.
- **Modifying API behavior**: Edit `src/steam_manifest/core/network.py`.
- **Adding new file processors**: Update `src/steam_manifest/core/storage.py`.
