"""Constants configuration module"""

from importlib.metadata import version
from typing import Final

# Version information (synced with pyproject.toml via importlib.metadata)
VERSION: Final[str] = version("steam-manifest")

# 网络配置 - 异步优化
DNS_SERVERS: Final[list[str]] = ["223.5.5.5"]
TIMEOUT: Final[int] = 30
RETRY_TIMES: Final[int] = 5  # 减少重试次数，使用指数退避
RETRY_INTERVAL: Final[float] = 1.0  # 基础重试间隔（秒）
MAX_WORKERS: Final[int] = 10  # 异步并发数（远高于线程池）

# 异步配置
ASYNC_TIMEOUT: Final[int] = 30
CONNECTOR_LIMIT: Final[int] = 100  # 连接池大小
CONNECTOR_LIMIT_PER_HOST: Final[int] = 10

# 缓存配置
CACHE_MAX_SIZE: Final[int] = 500  # API响应缓存数量
CACHE_TTL: Final[int] = 3600  # 缓存时间（秒）


class Urls:
    """URL常量管理"""

    GITHUB_API: Final[str] = "https://api.github.com"
    GITHUB_RAW: Final[str] = "https://raw.githubusercontent.com"
    GITHUB_RATE_LIMIT: Final[str] = f"{GITHUB_API}/rate_limit"

    # Steam相关
    STEAM_STORE: Final[str] = "https://store.steampowered.com/api"
    STEAM_SEARCH: Final[str] = f"{STEAM_STORE}/storesearch"
    STEAM_APP_DETAILS: Final[str] = f"{STEAM_STORE}/appdetails"

    @staticmethod
    def github_branch(repo: str, branch: str) -> str:
        """获取GitHub分支URL"""
        return f"{Urls.GITHUB_API}/repos/{repo}/branches/{branch}"

    @staticmethod
    def github_raw(repo: str, branch: str, path: str) -> str:
        """获取GitHub原始内容URL"""
        return f"{Urls.GITHUB_RAW}/{repo}/{branch}/{path}"

    @staticmethod
    def steam_search(term: str) -> str:
        """获取Steam搜索URL"""
        return f"{Urls.STEAM_SEARCH}/?cc=jp&l=zh&term={term}"

    @staticmethod
    def steam_app_details(appid: str) -> str:
        """获取Steam应用详情URL"""
        return f"{Urls.STEAM_APP_DETAILS}?cc=jp&l=zh&appids={appid}"


# HTTP请求头
HTTP_HEADERS: Final[dict[str, str]] = {
    "Accept": "application/json",
    "User-Agent": f"steam-manifest-cli/{VERSION}",
}

# 仓库配置
DEFAULT_REPOS: Final[list[str]] = ["SteamAutoCracks/ManifestHub"]


class Files:
    """文件相关常量"""

    MANIFEST_SUFFIX: Final[str] = ".manifest"
    CONFIG_JSON: Final[str] = "config.json"
    APPINFO_VDF: Final[str] = "appinfo.vdf"
    KEY_VDF: Final[str] = "key.vdf"
    STEAM_EXE: Final[str] = "steam.exe"


class Steam:
    """Steam相关常量"""

    REG_PATH: Final[str] = r"Software\Valve\Steam"
    REG_KEY: Final[str] = "SteamPath"
    PLUGIN_DIR: Final[str] = r"config\stplug-in"
    DEPOT_CACHE: Final[str] = r"config\depotcache"
