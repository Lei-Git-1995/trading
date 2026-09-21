"""AkShare 新浪数据提供者
- 全列表: stock_zh_a_spot  (约18秒, 5560+只；仅基本信息，无换手/量比/外盘/板块)
- 日K线:  stock_zh_a_daily  (新浪，含当日数据与换手率)
缺失字段: 换手率/量比/外盘内盘/行业板块 -> 换手率置空(自动跳过换手过滤)，外盘占比默认 50%
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .base import DataProvider, STOCK_COLS, register, retry_call
from .tencent_provider import _finalize_kline, _market_label, _strip_prefix, _to_symbol


@register
class AkshareSinaProvider(DataProvider):
    name = 'akshare'
    display = 'AkShare-新浪 (stock_zh_a_spot / stock_zh_a_daily)'

    def __init__(self, **kwargs):
        import akshare as ak
        self._ak = ak

    def get_all_stocks(self) -> pd.DataFrame:
        try:
            df = retry_call(self._ak.stock_zh_a_spot, retries=3, delay=5.0)
        except Exception:
            print('  新浪行情列表获取失败（限流或网络异常），返回空')
            return pd.DataFrame(columns=STOCK_COLS)
        if df is None or df.empty:
            return pd.DataFrame(columns=STOCK_COLS)

        df = df.copy()
        df['_code6'] = df['代码'].astype(str).map(lambda x: _strip_prefix(x)[0])
        df = df.drop_duplicates('_code6')
        df['_sector'] = df['_code6'].map(_market_label)

        out = pd.DataFrame({
            'code': df['_code6'],
            'name': df['名称'].astype(str),
            'price': df['最新价'].astype(float),
            'change_pct': df['涨跌幅'].astype(float),
            'turnover': np.nan,                      # 新浪列表不提供换手率
            'volume': df['成交量'].astype(float),
            'inner_vol': np.nan,
            'outer_vol': np.nan,
            'outer_ratio': np.nan,
            'inner_ratio': np.nan,
            'sector': df['_sector'],
        })
        return out[STOCK_COLS]

    def get_stock_history(self, code: str, days: int = 10):
        symbol = _to_symbol(str(code))
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=days * 2 + 5)).strftime('%Y%m%d')
        try:
            df = self._ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust='qfq')
        except Exception:
            return None
        if df is None or df.empty:
            return None
        df = df.tail(days).copy()
        return _finalize_kline(df, days)