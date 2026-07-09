"""异步API客户端模块 - 高性能网络请求处理"""

import asyncio
from typing import Any, cast

import aiohttp
import orjson
from aiohttp.resolver import AsyncResolver
from cachetools import TTLCache
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from steam_manifest.core.constants import (
    ASYNC_TIMEOUT,
    CACHE_MAX_SIZE,
    CACHE_TTL,
    CONNECTOR_LIMIT,
    CONNECTOR_LIMIT_PER_HOST,
    DNS_SERVERS,
    HTTP_HEADERS,
    MAX_WORKERS,
    RETRY_INTERVAL,
    RETRY_TIMES,
)
from steam_manifest.core.loghelper import log


class HttpClient:
    """异步API客户端，支持连接池、缓存和智能重试"""

    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        # Cache maps URL -> parsed JSON (usually dict)
        self.cache: TTLCache[str, Any] = TTLCache(maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL)
        self.request_count = 0
        self.cache_hits = 0

    async def __aenter__(self) -> "HttpClient":
        """异步上下文管理器入口"""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """异步上下文管理器出口"""
        await self.close()

    async def initialize(self) -> None:
        """初始化会话和连接池"""
        resolver = AsyncResolver(nameservers=DNS_SERVERS)

        connector = aiohttp.TCPConnector(
            limit=CONNECTOR_LIMIT,
            limit_per_host=CONNECTOR_LIMIT_PER_HOST,
            ttl_dns_cache=300,
            resolver=resolver,
        )
        timeout = aiohttp.ClientTimeout(total=ASYNC_TIMEOUT)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=HTTP_HEADERS,
            json_serialize=lambda x: orjson.dumps(x).decode(),
            trust_env=True,  # 自动读取系统环境变量代理设置 (HTTP_PROXY, HTTPS_PROXY)
        )
        log.debug("✨ 异步API客户端已初始化")

    async def close(self) -> None:
        """关闭会话"""
        if self.session:
            await self.session.close()
            log.debug("✨ 异步API客户端已关闭")
        log.info(
            f"📊 API统计 - 请求总数: {self.request_count}, "
            f"📊 缓存命中: {self.cache_hits}, "
            f"📊 命中率: {self.cache_hits / max(self.request_count, 1) * 100:.1f}%"
        )

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """发送HTTP请求，支持缓存和重试

        Args:
            method: HTTP方法 (GET, POST等)
            url: 请求URL
            **kwargs: 其他请求参数

        Returns:
            响应JSON或None
        """
        self.request_count += 1

        # 检查缓存（仅GET请求）
        if method.upper() == "GET" and url in self.cache:
            self.cache_hits += 1
            log.debug(f"💾 缓存命中: {url}")
            # cache stores Any, but callers expect dict[str, Any]
            return cast(dict[str, Any], self.cache[url])

        if not self.session:
            await self.initialize()

        # mypy can't infer that self.session is not None after initialize(), so
        # make a local copy and guard it for typing.
        session = self.session
        if session is None:
            log.error("❌ HTTP session is not initialized")
            return None

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(
                    (aiohttp.ClientError, asyncio.TimeoutError)
                ),
                stop=stop_after_attempt(RETRY_TIMES),
                wait=wait_exponential(multiplier=RETRY_INTERVAL, min=1, max=10),
                reraise=True,
            ):
                with attempt:
                    async with session.request(method, url, **kwargs) as response:
                        if response.status == 200:
                            data_any = await response.json(loads=orjson.loads)
                            data = cast(dict[str, Any], data_any)

                            # 缓存成功响应
                            if method.upper() == "GET":
                                self.cache[url] = data

                            return data
                        elif response.status == 429:  # Rate limit
                            reset_time = response.headers.get("X-RateLimit-Reset")
                            log.warning(f"⏱️ API速率限制，重置时间: {reset_time}")
                            raise aiohttp.ClientError("Rate limited")
                        else:
                            log.warning(f"❗ 请求失败 [{response.status}]: {url}")
                            raise aiohttp.ClientError(f"HTTP {response.status}")

        except RetryError:
            log.error(f"❌ 请求失败（已重试{RETRY_TIMES}次）: {url}")
            return None
        except Exception as e:
            log.error(f"❌ 请求异常: {str(e)}")
            return None
        # explicit fall-through return for mypy
        return None

    async def get(self, url: str, **kwargs: Any) -> dict[str, Any] | None:
        """发送GET请求"""
        return await self.request("GET", url, **kwargs)

    async def raw_get(self, url: str) -> Any:
        """获取原始二进制内容（用于下载文件）"""
        self.request_count += 1

        if not self.session:
            await self.initialize()

        session = self.session
        if session is None:
            log.error("❌ HTTP session is not initialized")
            return None

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(
                    (aiohttp.ClientError, asyncio.TimeoutError)
                ),
                stop=stop_after_attempt(RETRY_TIMES),
                wait=wait_exponential(multiplier=RETRY_INTERVAL, min=1, max=10),
                reraise=True,
            ):
                with attempt:
                    async with session.get(url) as response:
                        if response.status == 200:
                            return await response.read()
                        else:
                            raise aiohttp.ClientError(f"HTTP {response.status}")

        except RetryError:
            log.error(f"❌ 下载失败（已重试{RETRY_TIMES}次）: {url}")
            return None
        except Exception as e:
            log.error(f"❌ 下载异常: {str(e)}")
            return None
        # explicit fall-through return for mypy
        return None

    async def batch_get(
        self, urls: list[str], semaphore: asyncio.Semaphore | None = None
    ) -> dict[Any, Any] | dict[str, Any] | dict[str, str] | dict[bytes, bytes]:
        """批量GET请求，支持并发控制

        Args:
            urls: URL列表
            semaphore: 信号量，用于限制并发数

        Returns:
            {url: response} 字典
        """
        if semaphore is None:
            semaphore = asyncio.Semaphore(MAX_WORKERS)

        async def fetch_with_semaphore(url: str) -> tuple[str, dict[str, Any] | None]:
            async with semaphore:
                return url, await self.get(url)

        tasks = [fetch_with_semaphore(url) for url in urls]
        # return_exceptions=False means it will raise if any fail, but our get() handles exceptions and returns None
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # results is list[tuple[str, dict[str, Any] | None]]
        return dict(results)

    def clear_cache(self) -> None:
        """清空缓存"""
        self.cache.clear()
        log.debug("🗑️ 缓存已清空")
