"""Steam Manifest Tool Package"""

from importlib.metadata import version

from .cli import main

__version__ = version("steam-manifest")
__all__ = ["main", "__version__"]
