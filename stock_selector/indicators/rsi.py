"""RSI 相对强弱指标"""
import pandas as pd


def rsi(close: pd.Series, period: int = 6) -> pd.Series:
    """
    与原脚本一致的 RSI 计算：
      上行均值 / 下行均值 的标准化（窗口不足时按实际长度自适应）
    """
    close = close.astype(float)
    n = len(close)
    window = min(period, n)

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=window).mean()

    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def rsi6(close: pd.Series) -> pd.Series:
    """RSI(6)，短线默认周期"""
    return rsi(close, period=6)