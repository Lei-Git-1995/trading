"""高级技术指标：相对强度、均线位置、连续涨跌天数、突破检测等"""
from typing import Optional, Tuple, Dict
import pandas as pd
import numpy as np


def relative_strength(
    stock_change: float,
    sector_change: float
) -> float:
    """
    相对强度：个股表现相对于板块的强弱

    Args:
        stock_change: 个股涨跌幅(%)
        sector_change: 板块涨跌幅(%)

    Returns:
        相对强度(%)

    Examples:
        个股 +4%, 板块 +2% -> 相对强度 = +2%
        个股 +3%, 板块 +5% -> 相对强度 = -2%
    """
    return stock_change - sector_change


def ma_position(
    current_price: float,
    ma_price: float
) -> float:
    """
    均线位置：当前价格相对均线的位置百分比

    Args:
        current_price: 当前价格
        ma_price: 均线价格(如MA20)

    Returns:
        位置百分比(%)

    Examples:
        现价 10.5, MA20 10.0 -> +5%  (在均线上方5%)
        现价 9.5,  MA20 10.0 -> -5%  (在均线下方5%)
    """
    if ma_price == 0:
        return 0.0
    return (current_price - ma_price) / ma_price * 100


def consecutive_days(series: pd.Series, direction: str = 'up') -> int:
    """
    连续上涨/下跌天数

    Args:
        series: 涨跌幅序列(%)
        direction: 'up'=连续上涨, 'down'=连续下跌

    Returns:
        连续天数

    Examples:
        [+2, +3, +1, -2] -> 连续上涨3天
        [-1, -2, +3, +1] -> 连续下跌2天(当前不在连续中)
    """
    if series.empty:
        return 0

    count = 0
    for value in reversed(series.tolist()):
        if direction == 'up' and value > 0:
            count += 1
        elif direction == 'down' and value < 0:
            count += 1
        else:
            break

    return count


def recent_change(
    hist_data: pd.DataFrame,
    days: int = 5,
    price_col: str = '收盘'
) -> float:
    """
    近N日累计涨跌幅

    Args:
        hist_data: 历史数据
        days: 天数
        price_col: 价格列名

    Returns:
        累计涨跌幅(%)

    Examples:
        5日前收盘 10.0, 今日收盘 11.0 -> +10%
    """
    if len(hist_data) < days + 1:
        return 0.0

    current = hist_data[price_col].iloc[-1]
    previous = hist_data[price_col].iloc[-(days + 1)]

    if previous == 0:
        return 0.0

    return (current - previous) / previous * 100


def high_distance(
    current_price: float,
    today_high: float
) -> float:
    """
    距离日内最高价的距离

    Args:
        current_price: 当前价格
        today_high: 今日最高价

    Returns:
        距离百分比(%)

    Examples:
        现价 7.98, 最高 8.00 -> -0.25%  (距离最高价很近)
        现价 7.50, 最高 8.00 -> -6.25%  (明显回落)
    """
    if today_high == 0:
        return 0.0
    return (current_price - today_high) / today_high * 100


def breakout_detection(
    hist_data: pd.DataFrame,
    lookback_days: int = 20,
    price_col: str = '收盘',
    threshold: float = 0.0
) -> Tuple[bool, Optional[float]]:
    """
    突破检测：判断是否突破近期高点

    Args:
        hist_data: 历史数据
        lookback_days: 回看天数
        price_col: 价格列名
        threshold: 突破阈值(%), 0表示必须高于历史最高

    Returns:
        (是否突破, 突破幅度%)

    Examples:
        当前价 11.0, 20日最高 10.5 -> (True, +4.76%)
        当前价 10.2, 20日最高 10.5 -> (False, -2.86%)
    """
    if len(hist_data) < lookback_days + 1:
        return False, None

    # 当前价格
    current = hist_data[price_col].iloc[-1]

    # 回看期内的最高价(不包括今日)
    lookback_high = hist_data[price_col].iloc[-(lookback_days + 1):-1].max()

    if lookback_high == 0:
        return False, None

    # 计算突破幅度
    breakout_pct = (current - lookback_high) / lookback_high * 100

    # 判断是否突破
    is_breakout = breakout_pct >= threshold

    return is_breakout, breakout_pct


def platform_detection(
    hist_data: pd.DataFrame,
    lookback_days: int = 20,
    price_col: str = '收盘',
    tolerance: float = 5.0
) -> Tuple[bool, Optional[Dict]]:
    """
    平台检测：判断是否经历横盘整理后突破

    平台特征:
    1. 一段时间内价格波动较小(在tolerance范围内)
    2. 当前价格突破平台上沿

    Args:
        hist_data: 历史数据
        lookback_days: 回看天数
        price_col: 价格列名
        tolerance: 平台容忍波动(%)

    Returns:
        (是否存在平台突破, 平台信息)

    平台信息:
        {
            'platform_high': 平台上沿,
            'platform_low': 平台下沿,
            'platform_range': 平台波动幅度(%),
            'breakout_pct': 突破幅度(%)
        }
    """
    if len(hist_data) < lookback_days + 1:
        return False, None

    # 回看期数据(不包括今日)
    lookback_prices = hist_data[price_col].iloc[-(lookback_days + 1):-1]
    current_price = hist_data[price_col].iloc[-1]

    platform_high = lookback_prices.max()
    platform_low = lookback_prices.min()
    platform_mid = (platform_high + platform_low) / 2

    if platform_mid == 0:
        return False, None

    # 平台波动幅度
    platform_range = (platform_high - platform_low) / platform_mid * 100

    # 判断是否形成平台(波动幅度小于tolerance)
    is_platform = platform_range <= tolerance

    if not is_platform:
        return False, None

    # 判断是否突破平台上沿
    breakout_pct = (current_price - platform_high) / platform_high * 100
    is_breakout = breakout_pct >= 0

    if not is_breakout:
        return False, None

    return True, {
        'platform_high': platform_high,
        'platform_low': platform_low,
        'platform_range': platform_range,
        'breakout_pct': breakout_pct
    }


def momentum_acceleration(
    hist_data: pd.DataFrame,
    change_col: str = '涨跌幅'
) -> bool:
    """
    动能加速：今日涨幅明显强于昨日

    用于识别"弱转强"信号

    Args:
        hist_data: 历史数据
        change_col: 涨跌幅列名

    Returns:
        是否加速

    Examples:
        昨日 -2%, 今日 +5% -> True
        昨日 +3%, 今日 +1% -> False
    """
    if len(hist_data) < 2:
        return False

    today_change = hist_data[change_col].iloc[-1]
    yesterday_change = hist_data[change_col].iloc[-2]

    # 动能加速：今日涨幅 > 昨日涨幅 + 2%
    return today_change > yesterday_change + 2.0


def volume_expansion(
    hist_data: pd.DataFrame,
    days: int = 5,
    volume_col: str = '成交量',
    threshold: float = 1.5
) -> Tuple[bool, Optional[float]]:
    """
    成交量突然放大

    Args:
        hist_data: 历史数据
        days: 对比天数
        volume_col: 成交量列名
        threshold: 放大倍数阈值

    Returns:
        (是否放大, 放大倍数)
    """
    if len(hist_data) < days + 1:
        return False, None

    current_vol = hist_data[volume_col].iloc[-1]
    avg_vol = hist_data[volume_col].iloc[-(days + 1):-1].mean()

    if avg_vol == 0:
        return False, None

    ratio = current_vol / avg_vol
    is_expanded = ratio >= threshold

    return is_expanded, ratio


def calculate_ma(
    hist_data: pd.DataFrame,
    period: int = 20,
    price_col: str = '收盘'
) -> Optional[float]:
    """
    计算均线

    Args:
        hist_data: 历史数据
        period: 周期
        price_col: 价格列名

    Returns:
        均线值
    """
    if len(hist_data) < period:
        return None

    return hist_data[price_col].iloc[-period:].mean()


def ma_trend(
    hist_data: pd.DataFrame,
    period: int = 20,
    price_col: str = '收盘'
) -> str:
    """
    判断均线趋势

    Args:
        hist_data: 历史数据
        period: 均线周期
        price_col: 价格列名

    Returns:
        'up'/'down'/'flat'
    """
    if len(hist_data) < period + 5:
        return 'unknown'

    # 计算最近5日的均线
    ma_values = []
    for i in range(5):
        end_idx = -(i) if i > 0 else None
        start_idx = -(period + i)
        ma = hist_data[price_col].iloc[start_idx:end_idx].mean()
        ma_values.append(ma)

    # 反转，使其按时间顺序
    ma_values = ma_values[::-1]

    # 判断趋势
    if ma_values[-1] > ma_values[0] * 1.02:  # 上涨超过2%
        return 'up'
    elif ma_values[-1] < ma_values[0] * 0.98:  # 下跌超过2%
        return 'down'
    else:
        return 'flat'


def check_ma_support(
    current_price: float,
    ma_price: float,
    tolerance: float = 3.0
) -> bool:
    """
    检查是否在均线支撑位附近

    Args:
        current_price: 当前价格
        ma_price: 均线价格
        tolerance: 容忍范围(%)

    Returns:
        是否在支撑位

    Examples:
        现价 10.2, MA20 10.0, tolerance=3% -> True (在MA20上方2%)
        现价 9.6,  MA20 10.0, tolerance=3% -> False (在MA20下方4%)
    """
    if ma_price == 0:
        return False

    pos = ma_position(current_price, ma_price)

    # 在均线上下tolerance范围内
    return -tolerance <= pos <= tolerance
