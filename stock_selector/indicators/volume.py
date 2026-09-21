"""量能指标：放量倍数计算"""
import numpy as np
import pandas as pd


def prev_avg_volume(volumes: pd.Series, lookback: int = 2) -> float:
    """
    前 lookback 个交易日的平均成交量（默认前两日平均）。
    数据不足 lookback 时返回 NaN。
    """
    volumes = volumes.astype(float).reset_index(drop=True)
    if len(volumes) < lookback:
        return float('nan')
    return float(volumes.iloc[-1 - lookback:-1].mean())


def volume_ratio(volumes: pd.Series, lookback: int = 2) -> float:
    """
    当日成交量 / 前 lookback 日均量，返回放量倍数。
    前日无成交或数据不足时返回 NaN。
    """
    base = prev_avg_volume(volumes, lookback)
    latest = float(volumes.astype(float).iloc[-1]) if len(volumes) else float('nan')
    if np.isnan(base) or base <= 0:
        return float('nan')
    return latest / base


def check_volume_boost(volumes: pd.Series, threshold: float, lookback: int = 2):
    """
    判断是否放量。返回 (倍数, 是否满足条件)。
    倍数 3 项: [倍数, bool]
    """
    ratio = volume_ratio(volumes, lookback)
    if np.isnan(ratio):
        return ratio, False
    return ratio, ratio >= threshold