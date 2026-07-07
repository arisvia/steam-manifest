# Steam Manifest Tool

A high-performance asynchronous CLI tool for retrieving Steam manifest files from GitHub repositories.

## Features

- Async/await based for high performance
- Automatic Steam installation detection (Windows)
- Steam app search by name or ID
- DLC support with automatic detection
- GitHub API rate limit handling
- Progress bars and colorful output

## Installation

### Using uv (Recommended)

```bash
# Install from source
uv pip install -e .

# Or install from PyPI (when published)
uv pip install steam-manifest
```

### Using pip

```bash
# Install from source
pip install -e .

# Or install from PyPI
pip install steam-manifest
```

## Usage

```bash
# Search by app name
steam-manifest -a "Hollow Knight"

# Search by app ID
steam-manifest -a 367520

# Debug mode
steam-manifest -a 367520 -d

# Use custom GitHub repository
steam-manifest -a 367520 -r "YourRepo/ManifestHub"

# Enable fixed manifest mode
steam-manifest -a 367520 -f

# Use GitHub API token (increases rate limit)
steam-manifest -a 367520 -k YOUR_GITHUB_TOKEN
```

## Options

| Option | Description |
|--------|-------------|
| `-a, --appid` | Steam app ID or name |
| `-k, --key` | GitHub API access token |
| `-r, --repo` | Custom GitHub repository name |
| `-f, --fixed` | Enable fixed manifest mode |
| `-d, --debug` | Enable debug logging |
| `-v, --version` | Show version |

## Requirements

- Python 3.12+
- Steam installed (Windows only for auto-detection)

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run linting
ruff check src/

# Run type checking
mypy src/

# Run tests
pytest
```

## License

MIT License
