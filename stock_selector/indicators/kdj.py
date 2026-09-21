"""KDJ 随机指标"""
import pandas as pd


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9) -> dict:
    """
    计算 KDJ，返回 {'K': Series, 'D': Series, 'J': Series}
    原脚本仅使用 K，这里一并给出 K/D/J。
    """
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)

    n = len(close)
    window = min(period, n)

    low_list = low.rolling(window=window).min()
    high_list = high.rolling(window=window).max()
    rng = (high_list - low_list).replace(0, pd.NA)

    rsv = (close - low_list) / rng * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {'K': k, 'D': d, 'J': j}


def kdj_k(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9) -> pd.Series:
    """KDJ 的 K 值"""
    return kdj(high, low, close, period)['K']