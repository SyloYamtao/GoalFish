"""
日志配置模块
提供统一的日志管理，同时输出到控制台和文件
"""

import os
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _ensure_utf8_stdout():
    """
    确保 stdout/stderr 使用 UTF-8 编码
    解决 Windows 控制台中文乱码问题
    """
    if sys.platform == 'win32':
        # Windows 下重新配置标准输出为 UTF-8
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# 日志目录：项目根目录 logs/
LOG_DIR = os.path.join(_project_root(), 'logs')


class LogbackStyleFormatter(logging.Formatter):
    """
    将 Python 日志格式化成接近 Spring Boot/logback 的控制台格式。

    对应的 logback pattern 大致是：
    %d{yyyy-MM-dd HH:mm:ss.SSS} %5p ${PID} [%t] [%-40.40logger{39}:%line] : %m%n%wEx

    注意：logback 的 %clr(...) 是控制台颜色能力，不适合直接写入日志文件。
    本 formatter 支持颜色，但默认关闭，避免文件日志里出现 ANSI 转义字符。
    """

    LOGGER_WIDTH = 40
    _RESET = "\033[0m"
    _STYLE_CODES = {
        "faint": "\033[2m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
    }
    _LEVEL_COLORS = {
        "TRACE": "faint",
        "DEBUG": "green",
        "INFO": "green",
        "WARN": "yellow",
        "ERROR": "red",
        "CRITICAL": "red",
    }

    def __init__(self, *, use_color: bool = False):
        super().__init__()
        self.use_color = use_color

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        # logback 的 SSS 表示毫秒；Python 的 microsecond 是 6 位，这里截成 3 位。
        return datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self._color(self.formatTime(record), "faint")
        level = self._color(self._format_level(record), self._level_style(record))
        process_id = self._color(str(os.getpid()), "magenta")
        thread_name = self._color(f"[{record.threadName}]", "faint")
        logger_location = self._color(
            f"[{self._format_logger_name(record.name)}:{record.lineno}]",
            "cyan",
        )
        separator = self._color(":", "faint")

        message = record.getMessage()
        formatted = (
            f"{timestamp} {level} {process_id} {thread_name} "
            f"{logger_location} {separator} {message}"
        )

        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            formatted = f"{formatted}\n{record.exc_text}"
        if record.stack_info:
            formatted = f"{formatted}\n{self.formatStack(record.stack_info)}"
        return formatted

    def _format_level(self, record: logging.LogRecord) -> str:
        # Java/logback 常用 WARN；Python 默认是 WARNING，这里转换成更接近 logback 的写法。
        level_name = "WARN" if record.levelname == "WARNING" else record.levelname
        return f"{level_name:>5}"

    def _format_logger_name(self, logger_name: str) -> str:
        abbreviated = self._abbreviate_logger_name(logger_name)
        if len(abbreviated) > self.LOGGER_WIDTH:
            abbreviated = abbreviated[-self.LOGGER_WIDTH:]
        return f"{abbreviated:<{self.LOGGER_WIDTH}}"

    def _abbreviate_logger_name(self, logger_name: str) -> str:
        if len(logger_name) <= self.LOGGER_WIDTH:
            return logger_name

        parts = logger_name.split(".")
        if len(parts) == 1:
            return logger_name

        # 模拟 logback 的 logger{N} 思路：保留最后一段模块名，前面的包名逐步缩写。
        abbreviated_parts = parts[:]
        for index in range(len(abbreviated_parts) - 1):
            abbreviated_parts[index] = abbreviated_parts[index][:1]
            abbreviated = ".".join(abbreviated_parts)
            if len(abbreviated) <= self.LOGGER_WIDTH:
                return abbreviated
        return ".".join(abbreviated_parts)

    def _level_style(self, record: logging.LogRecord) -> str | None:
        level_name = "WARN" if record.levelname == "WARNING" else record.levelname
        return self._LEVEL_COLORS.get(level_name)

    def _color(self, value: str, style: str | None) -> str:
        if not self.use_color or not style:
            return value
        code = self._STYLE_CODES.get(style)
        if not code:
            return value
        return f"{code}{value}{self._RESET}"


def _startup_time() -> str:
    startup_time = os.environ.get('GOALFISH_STARTUP_TIME')
    if not startup_time:
        startup_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    os.environ['GOALFISH_STARTUP_TIME'] = startup_time
    return startup_time


def _parse_log_level(value: str | None, default: int) -> int:
    if not value:
        return default
    normalized = value.strip().upper()
    if normalized.isdigit():
        return int(normalized)
    return getattr(logging, normalized, default)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_goalfish_env(name: str) -> str | None:
    return os.environ.get(f'GOALFISH_{name}')


def setup_logger(name: str = 'goalfish', level: int = logging.DEBUG) -> logging.Logger:
    """
    设置日志器
    
    Args:
        name: 日志器名称
        level: 日志级别
        
    Returns:
        配置好的日志器
    """
    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # 创建日志器
    logger = logging.getLogger(name)
    logger_level = _parse_log_level(_get_goalfish_env('LOG_LEVEL'), level)
    file_level = _parse_log_level(_get_goalfish_env('FILE_LOG_LEVEL'), logging.DEBUG)
    console_level = _parse_log_level(_get_goalfish_env('CONSOLE_LOG_LEVEL'), logging.DEBUG)
    logger.setLevel(logger_level)
    
    # 阻止日志向上传播到根 logger，避免重复输出
    logger.propagate = False
    
    # 如果已经有处理器，不重复添加
    if logger.handlers:
        return logger
    
    # 日志格式：与 Spring Boot/logback 默认控制台布局保持一致。
    # 文件日志默认不带 ANSI 颜色，控制台颜色可以通过 GOALFISH_LOG_COLOR=1 开启。
    detailed_formatter = LogbackStyleFormatter(use_color=False)
    simple_formatter = LogbackStyleFormatter(
        use_color=_parse_bool(_get_goalfish_env('LOG_COLOR'), default=False)
    )
    
    # 1. 文件处理器 - 详细日志（按进程启动时间命名，带轮转）
    log_filename = f"{_startup_time()}-app.log"
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, log_filename),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(detailed_formatter)
    
    # 2. 控制台处理器 - 简洁日志
    # 确保 Windows 下使用 UTF-8 编码，避免中文乱码
    _ensure_utf8_stdout()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(simple_formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str = 'goalfish') -> logging.Logger:
    """
    获取日志器（如果不存在则创建）
    
    Args:
        name: 日志器名称
        
    Returns:
        日志器实例
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


# 创建默认日志器
logger = setup_logger()


# 便捷方法
def debug(msg: str, *args, **kwargs) -> None:
    logger.debug(msg, *args, **kwargs)

def info(msg: str, *args, **kwargs) -> None:
    logger.info(msg, *args, **kwargs)

def warning(msg: str, *args, **kwargs) -> None:
    logger.warning(msg, *args, **kwargs)

def error(msg: str, *args, **kwargs) -> None:
    logger.error(msg, *args, **kwargs)

def critical(msg: str, *args, **kwargs) -> None:
    logger.critical(msg, *args, **kwargs)
