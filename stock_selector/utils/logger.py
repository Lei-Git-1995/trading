"""
日志系统：统一的日志管理

用法：
    from stock_selector.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info('开始执行...')
"""
import logging
import sys
from pathlib import Path
from datetime import datetime

# 日志颜色配置（可选，Windows需要colorama支持）
try:
    import colorama
    colorama.init()
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',    # 红色
        'CRITICAL': '\033[35m', # 紫色
        'RESET': '\033[0m'
    }
except ImportError:
    COLORS = {k: '' for k in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'RESET']}


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""

    def format(self, record):
        levelname = record.levelname
        if COLORS.get(levelname):
            record.levelname = f"{COLORS[levelname]}{levelname}{COLORS['RESET']}"
        return super().format(record)


class _StdoutHandler(logging.StreamHandler):
    """始终输出到当前的 sys.stdout（无则 sys.stderr）。

    打包为无控制台窗口程序时，导入阶段 sys.stdout 可能为 None。
    若在导入期就绑定固定的 stream，GUI 事后重定向 stdout 也不会生效，
    导致所有日志被静默丢弃。此处理器在每次 emit 时动态解析 stream。
    """

    def emit(self, record):
        stream = sys.stdout or sys.stderr
        if stream is None:
            return
        self.stream = stream
        try:
            super().emit(record)
        except Exception:  # noqa: BLE001
            self.handleError(record)


# 全局日志配置
_initialized = False
_log_level = logging.INFO
_log_file = None


def setup_logger(level=logging.INFO, log_file=None, enable_color=True, force=False):
    """
    初始化全局日志配置

    Args:
        level: 日志级别（logging.DEBUG/INFO/WARNING/ERROR）
        log_file: 日志文件路径（None则不写文件）
        enable_color: 是否启用彩色输出
        force: 忽略已初始化状态，强制按当前参数重建处理器（GUI 去色时使用）
    """
    global _initialized, _log_level, _log_file

    if _initialized and not force:
        return

    _log_level = level
    _log_file = log_file

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有的处理器
    root_logger.handlers.clear()

    # 控制台处理器 - 动态解析 sys.stdout（兼容无控制台打包环境）
    console_handler = _StdoutHandler()
    console_handler.setLevel(level)

    # 尝试设置UTF-8编码
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

    if enable_color and COLORS.get('RESET'):
        console_formatter = ColoredFormatter(
            '%(levelname)s - %(message)s'
        )
    else:
        console_formatter = logging.Formatter(
            '%(levelname)s - %(message)s'
        )

    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器（如果指定了日志文件）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)

        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    _initialized = True


def get_logger(name):
    """
    获取日志记录器

    Args:
        name: 日志记录器名称（通常使用 __name__）

    Returns:
        logging.Logger
    """
    # 如果未初始化，使用默认配置
    if not _initialized:
        setup_logger()

    return logging.getLogger(name)


def get_default_log_file():
    """获取默认日志文件路径"""
    from stock_selector.config import PROJECT_ROOT
    log_dir = PROJECT_ROOT / 'logs'
    log_dir.mkdir(exist_ok=True)
    return str(log_dir / f'{datetime.now().strftime("%Y-%m-%d")}.log')
