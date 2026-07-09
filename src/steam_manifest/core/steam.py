"""Steam应用信息管理模块"""

from rich.console import Console
from rich.table import Table

from steam_manifest.core.constants import Urls
from steam_manifest.core.loghelper import log
from steam_manifest.core.network import HttpClient


class SteamApp:
    """Steam应用信息管理器"""

    def __init__(self, api_client: HttpClient) -> None:
        self.api_client = api_client
        self.app_id: str = ""
        self.app_name: str | None = None
        self.dlc_ids: list[int] = []

    async def search_app(self, query: str) -> int | None:
        """搜索Steam应用

        Args:
            query: 应用名称或ID

        Returns:
            应用ID或None
        """
        # 如果输入是纯数字，直接返回
        if query.isdigit():
            self.app_id = query
            return int(query)

        # 搜索应用
        try:
            search_url = Urls.steam_search(query)
            result = await self.api_client.get(search_url)

            if not result or "items" not in result:
                log.error("❌ 未找到匹配的应用")
                return None

            items = result["items"]
            if not items:
                log.error("❌ 搜索结果为空")
                return None

            # 如果只有一个结果，直接选择
            if len(items) == 1:
                app_id = int(items[0]["id"])
                self.app_id = str(app_id)
                log.info(f"✨ 已选择应用: [{app_id}] {items[0]['name']}")
                return app_id

            # 多个结果，显示列表
            console = Console()
            table = Table(title="🎯 搜索结果")
            table.add_column("序号", style="cyan", justify="right")
            table.add_column("AppID", style="magenta")
            table.add_column("名称", style="green")
            table.add_column("类型", style="yellow")

            for idx, item in enumerate(items[:10], 1):  # 最多显示10个
                item_type = item.get("type", "unknown")
                table.add_row(str(idx), str(item["id"]), item["name"], item_type)

            console.print(table)

            # 让用户选择
            while True:
                try:
                    choice = input("请选择应用序号 (1-10): ").strip()
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(items[:10]):
                        app_id = int(items[choice_idx]["id"])
                        self.app_id = str(app_id)
                        log.info(
                            f"✨ 已选择应用: [{app_id}] {items[choice_idx]['name']}"
                        )
                        return app_id
                    else:
                        log.warning("❗ 输入无效，请重新选择")
                except (ValueError, KeyboardInterrupt):
                    log.warning("❗ 输入无效，请重新选择")

        except Exception as e:
            log.error(f"❌ 搜索应用失败: {str(e)}")
            return None

    async def fetch_app_details(self, app_id: str) -> bool:
        """获取应用详情（包括名称和DLC）

        Args:
            app_id: 应用ID

        Returns:
            是否成功获取
        """
        try:
            detail_url = Urls.steam_app_details(app_id)
            result = await self.api_client.get(detail_url)

            if not result or not isinstance(result, dict):
                log.warning("❗ 无法获取应用详情")
                return False

            app_data = result.get(app_id, {})
            if not app_data.get("success"):
                log.warning(f"❗ 应用 {app_id} 不存在或无法访问")
                return False

            data = app_data.get("data", {})
            self.app_name = data.get("name")
            self.dlc_ids = data.get("dlc", [])

            if self.app_name:
                log.info(f"📦 应用名称: {self.app_name}")

            if self.dlc_ids:
                log.info(f"🎮 发现 {len(self.dlc_ids)} 个DLC")

            return True

        except Exception as e:
            log.error(f"❌ 获取应用详情失败: {str(e)}")
            return False

    async def batch_fetch_dlc_details(self, dlc_ids: list[int]) -> dict[int, str]:
        """批量获取DLC详情

        Args:
            dlc_ids: DLC ID列表

        Returns:
            {dlc_id: app_name} 字典
        """
        if not dlc_ids:
            return {}

        # 构建多个DLC的URL
        urls = [Urls.steam_app_details(str(dlc_id)) for dlc_id in dlc_ids]

        # 批量获取
        results = await self.api_client.batch_get(urls)

        dlc_names = {}
        for url, data in results.items():
            if not data or not isinstance(data, dict):
                continue
            # 从URL中提取DLC ID
            dlc_id = str(url).split("appids=")[-1]
            if dlc_id.isdigit():
                app_data = data.get(dlc_id, {})
                if isinstance(app_data, dict) and app_data.get("success"):
                    app_name = app_data.get("data", {}).get("name", "Unknown")
                    dlc_names[int(dlc_id)] = app_name

        return dlc_names

    def clear(self) -> None:
        """清空数据"""
        self.app_id = ""
        self.app_name = None
        self.dlc_ids.clear()
