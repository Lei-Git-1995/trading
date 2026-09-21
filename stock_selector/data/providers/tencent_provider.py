"""腾讯数据提供者：经 akshare 调用腾讯接口
- 全列表: stock_zh_a_spot_tx  (约8秒, 5560+只, 含换手/量比)
- 日K线:  stock_zh_a_hist_tx  (含当日数据与换手率)
缺失字段: 外盘/内盘、行业板块 -> 外盘占比默认 50%，板块降级为按代码推断的市场类别
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .base import DataProvider, STOCK_COLS, register, retry_call


def _strip_prefix(code: str) -> tuple[str, str]:
    """'sh600664' -> ('600664','sh')；无前缀时返回 (原值, '')"""
    for p in ('sh', 'sz', 'bj'):
        if str(code).lower().startswith(p):
            return str(code)[2:], p
    return str(code), ''


def _market_label(code6: str) -> str:
    """按代码段推断市场类别，用作板块字段（数据源不提供行业板块）"""
    if code6.startswith('688'):
        return '科创板'
    if code6.startswith(('300', '301')):
        return '创业板'
    if code6.startswith(('600', '601', '603', '605')):
        return '上证主板'
    if code6.startswith(('000', '001', '002', '003')):
        return '深证主板'
    if code6.startswith(('4', '8', '92')):
        return '北交所'
    return '其他'


def _to_symbol(code6: str) -> str:
    """600664 -> sh600664 / 000001 -> sz000001"""
    if code6.startswith('6') or code6.startswith('9'):
        m = 'sh'
    elif code6.startswith(('4', '8', '92')):
        m = 'bj'
    else:
        m = 'sz'
    return f'{m}{code6}'


@register
class TencentProvider(DataProvider):
    name = 'tencent'
    display = '腾讯 (经 akshare: stock_zh_a_spot_tx / stock_zh_a_hist_tx)'

    def __init__(self, **kwargs):
        import akshare as ak
        self._ak = ak

    def get_all_stocks(self) -> pd.DataFrame:
        try:
            df = retry_call(self._ak.stock_zh_a_spot_tx, retries=3, delay=5.0)
        except Exception:
            print('  腾讯行情列表获取失败（限流或网络异常），返回空')
            return pd.DataFrame(columns=STOCK_COLS)
        if df is None or df.empty:
            return pd.DataFrame(columns=STOCK_COLS)

        df = df.copy()
        df['_code6'] = df['code'].astype(str).map(lambda x: _strip_prefix(x)[0])
        df = df.drop_duplicates('_code6')
        df['_sector'] = df['_code6'].map(_market_label)

        out = pd.DataFrame({
            'code': df['_code6'],
            'name': df['name'].astype(str),
            'price': df['zxj'].astype(float),
            'change_pct': df['zdf'].astype(float),
            'turnover': df['hsl'].astype(float),
            'volume': df['volume'].astype(float),
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
            df = self._ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start, end_date=end, adjust='qfq')
        except Exception:
            return None
        if df is None or df.empty:
            return None
        df = df.tail(days).copy()
        return _finalize_kline(df)


def _finalize_kline(df: pd.DataFrame, days: int = None):
    """腾讯 hist_tx 结果补全为标准 K 线列（成交量股->手，补涨幅/振幅/换手率）"""
    out = pd.DataFrame({
        '日期': df['date'].astype(str),
        '开盘': df['open'].astype(float),
        '收盘': df['close'].astype(float),
        '最高': df['high'].astype(float),
        '最低': df['low'].astype(float),
        '成交量': df['volume'].astype(float) / 100,          # 股 -> 手
        '成交额': df['amount'].astype(float),
        '换手率': df['turnover'].astype(float) * 100,        # 小数 -> %
    })
    out['涨跌额'] = out['收盘'].diff()
    out['涨跌幅'] = out['收盘'].pct_change() * 100
    out['振幅'] = (out['最高'] - out['最低']) / out['收盘'].shift(1) * 100
    out = out.fillna({'涨跌额': 0.0, '涨跌幅': 0.0, '振幅': 0.0})
    if days is not None:
        out = out.tail(days)
    return out.reset_index(drop=True)