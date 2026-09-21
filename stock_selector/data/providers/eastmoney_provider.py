"""东方财富数据提供者：复用现有 EastMoneyClient，K线不可达时自动回退腾讯"""
import pandas as pd

from stock_selector.data.eastmoney_client import EastMoneyClient
from stock_selector.data.stock_list import load_stock_list
from .base import DataProvider, STOCK_COLS, register


@register
class EastMoneyProvider(DataProvider):
    name = 'eastmoney'
    display = '东方财富 (直连 clist/push2his，K线不可达回退腾讯)'

    def __init__(self, **kwargs):
        self._client = EastMoneyClient(**kwargs)

    def get_all_stocks(self) -> pd.DataFrame:
        raw = self._client.get_all_stocks()
        if raw is None or raw.empty:
            return pd.DataFrame(columns=STOCK_COLS)
        df = load_stock_list(raw)
        return df[STOCK_COLS] if len(df) else df

    def get_stock_history(self, code: str, days: int = 10):
        return self._client.get_stock_history(code, days)