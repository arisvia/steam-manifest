"""Steam清单获取工具 - 高性能异步版本"""

import asyncio
import sys
from argparse import ArgumentParser, Namespace
from contextlib import suppress
from pathlib import Path
from time import sleep

from rich.console import Console
from rich.text import Text

from steam_manifest.core.constants import VERSION, Steam
from steam_manifest.core.github import GitHubRepo
from steam_manifest.core.loghelper import log, setup_logger
from steam_manifest.core.network import HttpClient
from steam_manifest.core.steam import SteamApp
from steam_manifest.core.storage import ManifestStorage


def show_banner() -> None:
    """显示应用欢迎banner"""
    console = Console()

    banner_text = Text()
    banner_text.append(
        r"""
     ('-. .-.   ('-.  _  .-')   .-') _      ('-.
    ( OO )  / _(  OO)( \( -O ) (  OO) )    ( OO ).-.
    ,--. ,--.(,------.,------. /     '._   / . --. /
    |  | |  | |  .---'|   /`. '|'--...__)  | \-.  \
    |   .|  | |  |    |  /  | |'--.  .--'.-'-'  |  |
    |       |(|  '--. |  |_.' |   |  |    \| |_.'  |
    |  .-.  | |  `---.|  .  '.'   |  |     |  .-.  |
    |  | |  | |  `---.|  |\  \    |  |     |  | |  |
    `--' `--' `------'`--' '--'   `--'     `--' `--'
    """,
        style="bold magenta",
    )

    content = Text.assemble(
        banner_text,
        "\n",
        (rf"🚀 Steam manifest v{VERSION}", "bold cyan"),
        "\n",
        (r"💨 Powered by Python & AsyncIO", "dim white"),
        "\n",
    )

    console.print(content)


def init_command_args() -> Namespace:
    """初始化命令行参数"""
    parser = ArgumentParser(description="🚀 Steam 清单文件获取工具 v" + VERSION)
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s v{VERSION}"
    )
    parser.add_argument("-a", "--appid", help="🎮 Steam 应用ID或名称")
    parser.add_argument("-k", "--key", help="🔑 GitHub API 访问密钥")
    parser.add_argument("-r", "--repo", help="📁 自定义 GitHub 仓库名称")
    parser.add_argument(
        "-f", "--fixed", action="store_true", help="📌 启用固定清单模式"
    )
    # 日志控制参数
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="📝 日志级别 (默认: INFO)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="📂 日志文件目录 (默认: ./logs)",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="🚫 禁用日志输出",
    )
    # 保留 -d/--debug 作为快捷方式
    parser.add_argument(
        "-d", "--debug", action="store_true", help="🔍 调试模式 (等同于 --log-level DEBUG)"
    )
    return parser.parse_args()


def verify_steam_path() -> Path | None:
    """验证Steam安装路径"""
    try:
        if sys.platform != "win32":
            # For non-Windows platforms, checking registry won't work.
            # You might want to add logic for Linux/macOS or just skip auto-detection.
            # For now, return None or a default path if known.
            return None

        # Import winreg lazily to avoid import-time failures on non-Windows CI runners
        import winreg

        hkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, Steam.REG_PATH)
        steam_path = Path(winreg.QueryValueEx(hkey, Steam.REG_KEY)[0])

        if (steam_path / "steam.exe").exists():
            return steam_path

        return None
    except (FileNotFoundError, OSError, ImportError):
        # NameError handles if winreg is not imported on non-Windows
        return None


async def async_main() -> None:
    """主程序入口"""
    show_banner()

    # 初始化
    args = init_command_args()
    
    # 配置日志系统
    log_level = "DEBUG" if args.debug else args.log_level
    console_enable = not args.no_log
    file_enable = not args.no_log
    
    setup_logger(
        log_level=log_level,
        log_dir=args.log_dir,
        console_enable=console_enable,
        file_enable=file_enable,
    )

    # 验证Steam路径
    steam_path = verify_steam_path()
    if not steam_path:
        log.error("❌ 未找到Steam安装路径")
        return

    log.info(f"🎮 已定位Steam安装路径: {steam_path}")

    # 创建异步客户端和管理器
    async with HttpClient() as api_client:
        try:
            # 初始化各个管理器
            storage = ManifestStorage()
            steam_app = SteamApp(api_client)
            github_repo = GitHubRepo(api_client, storage)

            # 获取应用ID
            if args.appid:
                app_query = args.appid
            else:
                sleep(0.5)
                app_query = Console().input("[cyan]请输入游戏名称或ID: [/cyan]")

            # 检查API速率限制 (移到用户输入之后，避免网络卡顿影响交互)
            if not await github_repo.check_rate_limit():
                log.error("❌ API请求次数已达上限，请稍后再试")
                return

            app_id = await steam_app.search_app(app_query)

            if not app_id:
                log.error("❌ 无法获取应用ID")
                return

            app_id_str = str(app_id)

            # 构建仓库列表
            custom_repos = [args.repo] if args.repo else None

            # 查找仓库
            repo = await github_repo.find_repository(app_id_str, custom_repos)

            if not repo:
                log.error(f"❌ 未找到包含应用 {app_id_str} 的仓库")
                return

            # 获取应用详情
            await steam_app.fetch_app_details(app_id_str)

            # 获取文件列表
            files = await github_repo.fetch_repository_files(repo, app_id_str)
            if not files:
                log.error("❌ 无法获取仓库文件")
                return

            # 并发处理所有文件
            log.info("⏳ 正在处理仓库文件...")
            success = await github_repo.process_files(
                repo, app_id_str, files, steam_path
            )

            if not success:
                log.warning("❗ 部分文件处理失败")

            # 保存配置
            save_success = await storage.save_lua_config(
                app_id_str,
                steam_app.app_name,
                steam_path,
                args.fixed,
            )

            if save_success:
                log.info(f"✅ 操作完成！应用: {steam_app.app_name or app_id_str}")
            else:
                log.error("❌ 保存配置失败")

            # 处理DLC
            if steam_app.dlc_ids:
                log.info(f"🎯 检测到 {len(steam_app.dlc_ids)} 个DLC，正在处理...")

                # 为DLC复用资源
                dlc_storage = ManifestStorage()
                dlc_repo_mgr = GitHubRepo(api_client, dlc_storage)

                for dlc_id in steam_app.dlc_ids:
                    dlc_id_str = str(dlc_id)
                    dlc_repo = await dlc_repo_mgr.find_repository(
                        dlc_id_str, custom_repos
                    )

                    if dlc_repo:
                        dlc_files = await dlc_repo_mgr.fetch_repository_files(
                            dlc_repo, dlc_id_str
                        )
                        if dlc_files:
                            # 清理之前的状态
                            dlc_storage.clear()

                            # 处理DLC文件（下载清单等）
                            await dlc_repo_mgr.process_files(
                                dlc_repo, dlc_id_str, dlc_files, steam_path
                            )

                            # 保存DLC配置
                            await dlc_storage.save_lua_config(
                                dlc_id_str,
                                None,
                                steam_path,
                                args.fixed,
                            )
                            log.info(f"✅ DLC {dlc_id_str} 处理完成")
                    else:
                        log.warning(f"❗ 未找到 DLC {dlc_id_str} 的仓库")

        except KeyboardInterrupt:
            log.warning("❗ 操作已被用户中断")
            sys.exit(1)
        except Exception as e:
            log.error(f"❌ 发生异常: {str(e)}")
            if args.debug:
                log.exception("异常详情:")
            sys.exit(1)

    # 完成提示
    if not args.appid:
        with suppress(Exception):
            Console().input("\n[dim]按回车键退出...[/dim]")


def main() -> None:
    """Entry point for the application script"""
    try:
        if sys.platform == "win32":
            # Windows specific event loop policy for subprocesses if needed
            # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            pass
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
