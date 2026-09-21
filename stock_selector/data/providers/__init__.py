"""数据提供者注册：东财 / 腾讯 / akshare(新浪)"""
from .base import (
    DataProvider,
    STOCK_COLS,
    KLINE_COLS,
    create_provider,
    interactive_select,
    list_providers,
    retry_call,
)
from . import eastmoney_provider  # noqa: F401  (注册)
from . import tencent_provider    # noqa: F401  (注册)
from . import akshare_provider    # noqa: F401  (注册)

__all__ = [
    'DataProvider', 'STOCK_COLS', 'KLINE_COLS',
    'create_provider', 'interactive_select', 'list_providers', 'retry_call',
]