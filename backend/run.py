"""
GoalFish Backend 启动入口
"""

import atexit
import os
import sys
import threading
from datetime import datetime
from typing import TextIO

# 解决 Windows 控制台中文乱码问题：在所有导入之前设置 UTF-8 编码
if sys.platform == 'win32':
    # 设置环境变量确保 Python 使用 UTF-8
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # 重新配置标准输出流为 UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TeeStream:
    """Mirror stdout/stderr to a startup log file while preserving console output."""

    def __init__(self, original: TextIO, log_file: TextIO, lock: threading.RLock):
        self._original = original
        self._log_file = log_file
        self._lock = lock
        self._goalfish_console_tee = True

    def write(self, data: str) -> int:
        with self._lock:
            written = self._original.write(data)
            self._log_file.write(data)
            return written

    def flush(self) -> None:
        with self._lock:
            self._original.flush()
            self._log_file.flush()

    def isatty(self) -> bool:
        return self._original.isatty()

    def fileno(self) -> int:
        return self._original.fileno()

    def reconfigure(self, *args, **kwargs):
        if hasattr(self._original, 'reconfigure'):
            return self._original.reconfigure(*args, **kwargs)
        return None

    @property
    def encoding(self):
        return getattr(self._original, 'encoding', 'utf-8')

    @property
    def errors(self):
        return getattr(self._original, 'errors', 'replace')

    def __getattr__(self, name: str):
        return getattr(self._original, name)


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_console_log_path(root_dir: str | None = None) -> str:
    existing_path = os.environ.get('GOALFISH_CONSOLE_LOG_FILE')
    if existing_path:
        return existing_path

    startup_time = os.environ.get('GOALFISH_STARTUP_TIME')
    if not startup_time:
        startup_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        os.environ['GOALFISH_STARTUP_TIME'] = startup_time

    root_dir = root_dir or project_root()
    log_path = os.path.join(root_dir, 'logs', f'{startup_time}.log')
    os.environ['GOALFISH_CONSOLE_LOG_FILE'] = log_path
    return log_path


def install_console_log_tee() -> str:
    log_path = resolve_console_log_path()
    if getattr(sys.stdout, '_goalfish_console_tee', False):
        return log_path

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_file = open(log_path, 'a', encoding='utf-8', buffering=1)
    lock = threading.RLock()
    sys.stdout = TeeStream(sys.stdout, log_file, lock)
    sys.stderr = TeeStream(sys.stderr, log_file, lock)
    atexit.register(log_file.flush)
    return log_path


def main():
    """主函数"""
    console_log_path = install_console_log_tee()

    from app import create_app
    from app.config import Config

    print(f"控制台日志文件: {console_log_path}")

    # 验证配置
    errors = Config.validate()
    if errors:
        print("配置错误:")
        for err in errors:
            print(f"  - {err}")
        print("\n请检查 .env 文件中的配置")
        sys.exit(1)
    
    # 创建应用
    app = create_app()
    
    # 获取运行配置
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG
    
    # 启动服务
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    main()
