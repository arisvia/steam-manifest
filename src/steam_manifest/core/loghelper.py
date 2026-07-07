"""日志系统模块 - 统一日志管理"""

import logging
import os
import sys
from pathlib import Path
from types import FrameType

from loguru import logger

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class InterceptHandler(logging.Handler):
    """
    拦截标准 logging 模块并转发到 loguru
    """

    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 Loguru 级别
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        # 查找调用者位置
        frame: FrameType | None = logging.currentframe()
        depth = 2
        while (
            frame is not None
            and getattr(frame, "f_code", None) is not None
            and frame.f_code.co_filename == logging.__file__
        ):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logger(
    log_level: str = "INFO",
    log_dir: Path | None = None,
    console_enable: bool = True,
    file_enable: bool = True,
) -> None:
    """
    配置日志系统

    Args:
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_dir: 日志文件目录，None 则使用默认 logs/ 目录
        console_enable: 是否启用控制台输出
        file_enable: 是否启用文件日志
    """
    # 规范化日志级别
    normalized_level = str(log_level or "INFO").upper()
    if normalized_level not in VALID_LOG_LEVELS:
        sys.stderr.write(
            f"Invalid log level '{normalized_level}', fallback to INFO\n"
        )
        normalized_level = "INFO"

    # 移除默认处理器
    logger.remove()

    # 确定日志目录
    if log_dir is None:
        default_log_dir = os.path.join(os.getcwd(), "logs")
        log_dir = Path(os.environ.get("STEAM_MANIFEST_LOG_DIR", default_log_dir))
    else:
        log_dir = Path(log_dir)

    # 日志轮转和保留配置
    rotation = os.environ.get("STEAM_MANIFEST_LOG_ROTATION", "10 MB")
    retention = os.environ.get("STEAM_MANIFEST_LOG_RETENTION", "1 week")

    # 环境变量控制开关
    env_console_enable = (
        os.environ.get("STEAM_MANIFEST_LOG_CONSOLE_ENABLE", "true").lower() == "true"
    )
    env_file_enable = (
        os.environ.get("STEAM_MANIFEST_LOG_FILE_ENABLE", "true").lower() == "true"
    )

    # 使用参数优先，环境变量作为后备
    console_enable = console_enable and env_console_enable
    file_enable = file_enable and env_file_enable

    # 配置控制台输出
    if console_enable:
        console_format = "<green>{time:HH:mm:ss}</green> | <level>{message}</level>"
        if normalized_level == "DEBUG":
            console_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            )
        logger.add(
            sys.stderr,
            format=console_format,
            level=normalized_level,
        )

    # 配置文件输出
    if file_enable:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / "steam_manifest.log"
            logger.add(
                str(log_file_path),
                rotation=rotation,
                retention=retention,
                level="DEBUG",  # 文件始终记录 DEBUG 级别
                encoding="utf-8",
                enqueue=True,  # 异步安全
                backtrace=True,
                diagnose=True,
            )
        except Exception as e:
            # 文件日志失败时回退到控制台
            sys.stderr.write(f"Failed to setup file logging: {e}\n")

    # 拦截标准 logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 静默特定日志器
    for logger_name in ["httpx", "urllib3", "asyncio", "aiohttp"]:
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False

        if normalized_level == "DEBUG":
            logging_logger.setLevel(logging.INFO)
        else:
            logging_logger.setLevel(logging.WARNING)


# 模块加载时自动初始化（使用环境变量）
_env_log_level = os.environ.get("STEAM_MANIFEST_LOG_LEVEL", "INFO").upper()
setup_logger(_env_log_level)

# 导出 logger 实例
log = logger
