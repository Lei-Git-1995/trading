"""数据提供者抽象基类与注册/工厂"""
import time
from abc import ABC, abstractmethod

import pandas as pd

# STOCK_COLS — 统一的股票列表输出列，各 provider 必须返回这些列（可多出，不可缺少）
STOCK_COLS = [
    'code', 'name', 'price', 'change_pct', 'turnover', 'volume',
    'inner_vol', 'outer_vol', 'outer_ratio', 'inner_ratio', 'sector',
]

# 标准 K 线列（get_stock_history 返回值必须包含这些列）
KLINE_COLS = ['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']


class DataProvider(ABC):
    """数据提供者接口"""

    name: str = ''
    display: str = ''

    @abstractmethod
    def get_all_stocks(self) -> pd.DataFrame:
        """获取沪深全A股实时快照，返回 STOCK_COLS 格式 DataFrame"""

    @abstractmethod
    def get_stock_history(self, code: str, days: int = 10) -> pd.DataFrame:
        """获取个股近N交易日K线，返回 KLINE_COLS 格式 DataFrame"""


# ---- 注册表 ----

_PROVIDERS: dict[str, type[DataProvider]] = {}


def register(cls: type[DataProvider]) -> type[DataProvider]:
    _PROVIDERS[cls.name] = cls
    return cls


def list_providers() -> list[tuple[str, str]]:
    """返回 [(name, display), ...]"""
    return [(cls.name, cls.display) for cls in _PROVIDERS.values()]


def create_provider(name: str, **kwargs) -> DataProvider:
    if name not in _PROVIDERS:
        raise ValueError(f'未知数据源: {name}，可选: {", ".join(_PROVIDERS)}')
    return _PROVIDERS[name](**kwargs)


def interactive_select() -> str:
    """交互式选择数据源，返回 name"""
    items = list_providers()
    print('\n可用数据源:')
    for i, (name, disp) in enumerate(items, 1):
        print(f'  {i}. {disp}')
    print()
    while True:
        raw = input(f'请选择数据源 [1-{len(items)}]，直接回车使用默认(1): ').strip()
        if not raw:
            return items[0][0]
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(items):
                return items[idx][0]
        except ValueError:
            pass
        print('输入无效，请重试')


def retry_call(fn, retries: int = 3, delay: float = 3.0):
    """调用 fn()，失败重试 retries 次（每次间隔 delay 秒），全部失败抛出最后一次异常"""
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retries - 1:
                print(f'  接口调用失败，{delay}秒后重试（{i + 1}/{retries - 1}）: {type(e).__name__}')
                time.sleep(delay)
    raise last
