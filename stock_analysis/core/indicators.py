#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标计算模块
统一实现常用技术指标的计算逻辑
"""

import pandas as pd
import numpy as np
from typing import List, Dict
from ..config import INDICATOR_PARAMS


class TechnicalIndicators:
    """技术指标计算器"""

    @staticmethod
    def calculate_ma(df: pd.DataFrame, periods: List[int] = None) -> pd.DataFrame:
        """
        计算移动平均线（Moving Average）

        :param df: 包含'收盘'列的DataFrame
        :param periods: 周期列表，默认[5, 10, 20, 60]
        :return: 添加了MA列的DataFrame
        """
        if periods is None:
            periods = INDICATOR_PARAMS['ma_periods']

        for period in periods:
            df[f'MA{period}'] = df['收盘'].rolling(window=period).mean()
        return df

    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = None, slow: int = None,
                       signal: int = None) -> pd.DataFrame:
        """
        计算MACD指标（Moving Average Convergence Divergence）

        :param df: 包含'收盘'列的DataFrame
        :param fast: 快速EMA周期
        :param slow: 慢速EMA周期
        :param signal: 信号线周期
        :return: 添加了MACD_DIF、MACD_DEA、MACD_BAR列的DataFrame
        """
        params = INDICATOR_PARAMS['macd']
        fast = fast or params['fast']
        slow = slow or params['slow']
        signal = signal or params['signal']

        ema_fast = df['收盘'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['收盘'].ewm(span=slow, adjust=False).mean()
        df['MACD_DIF'] = ema_fast - ema_slow
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=signal, adjust=False).mean()
        df['MACD_BAR'] = (df['MACD_DIF'] - df['MACD_DEA']) * 2
        return df

    @staticmethod
    def calculate_kdj(df: pd.DataFrame, n: int = None, m1: int = None,
                      m2: int = None) -> pd.DataFrame:
        """
        计算KDJ指标（Stochastic Oscillator）

        :param df: 包含'收盘'、'最高'、'最低'列的DataFrame
        :param n: RSV周期
        :param m1: K值平滑周期
        :param m2: D值平滑周期
        :return: 添加了KDJ_K、KDJ_D、KDJ_J列的DataFrame
        """
        params = INDICATOR_PARAMS['kdj']
        n = n or params['n']
        m1 = m1 or params['m1']
        m2 = m2 or params['m2']

        low_list = df['最低'].rolling(window=n, min_periods=1).min()
        high_list = df['最高'].rolling(window=n, min_periods=1).max()

        rsv = (df['收盘'] - low_list) / (high_list - low_list) * 100
        rsv = rsv.fillna(0)

        df['KDJ_K'] = rsv.ewm(com=m1-1, adjust=False).mean()
        df['KDJ_D'] = df['KDJ_K'].ewm(com=m2-1, adjust=False).mean()
        df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']

        return df

    @staticmethod
    def calculate_rsi(df: pd.DataFrame, periods: List[int] = None) -> pd.DataFrame:
        """
        计算RSI指标（Relative Strength Index）

        :param df: 包含'收盘'列的DataFrame
        :param periods: 周期列表，默认[6, 12, 24]
        :return: 添加了RSI列的DataFrame
        """
        if periods is None:
            periods = INDICATOR_PARAMS['rsi_periods']

        for period in periods:
            delta = df['收盘'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            df[f'RSI{period}'] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def calculate_boll(df: pd.DataFrame, n: int = None, k: float = None) -> pd.DataFrame:
        """
        计算布林带（Bollinger Bands）

        :param df: 包含'收盘'列的DataFrame
        :param n: 周期
        :param k: 标准差倍数
        :return: 添加了BOLL_MID、BOLL_UPPER、BOLL_LOWER、BOLL_WIDTH列的DataFrame
        """
        params = INDICATOR_PARAMS['boll']
        n = n or params['n']
        k = k or params['k']

        df['BOLL_MID'] = df['收盘'].rolling(window=n).mean()
        std = df['收盘'].rolling(window=n).std()
        df['BOLL_UPPER'] = df['BOLL_MID'] + k * std
        df['BOLL_LOWER'] = df['BOLL_MID'] - k * std
        df['BOLL_WIDTH'] = ((df['BOLL_UPPER'] - df['BOLL_LOWER']) / df['BOLL_MID'] * 100)
        return df

    @classmethod
    def calculate_all(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算所有技术指标

        :param df: 包含OHLCV数据的DataFrame
        :return: 添加了所有指标的DataFrame
        """
        df = cls.calculate_ma(df)
        df = cls.calculate_macd(df)
        df = cls.calculate_kdj(df)
        df = cls.calculate_rsi(df)
        df = cls.calculate_boll(df)
        return df

    @staticmethod
    def analyze_trend(df: pd.DataFrame) -> Dict:
        """
        趋势分析

        :param df: 包含技术指标的DataFrame
        :return: 分析结果字典
        """
        latest = df.iloc[-1]
        close = latest['收盘']

        # 均线排列
        ma_list = [(5, latest.get('MA5', 0)), (10, latest.get('MA10', 0)),
                   (20, latest.get('MA20', 0)), (60, latest.get('MA60', 0))]

        is_multi = all(ma_list[i][1] > ma_list[i+1][1]
                      for i in range(len(ma_list)-1)
                      if ma_list[i][1] > 0 and ma_list[i+1][1] > 0)
        is_bear = all(ma_list[i][1] < ma_list[i+1][1]
                     for i in range(len(ma_list)-1)
                     if ma_list[i][1] > 0 and ma_list[i+1][1] > 0)

        if is_multi:
            trend = "多头排列,趋势向上"
        elif is_bear:
            trend = "空头排列,趋势向下"
        else:
            trend = "均线纠缠,趋势不明"

        # MACD分析
        macd_signal = "金叉" if latest['MACD_DIF'] > latest['MACD_DEA'] else "死叉"
        macd_status = "看多" if latest['MACD_BAR'] > 0 else "看空"

        # KDJ分析
        kdj_k = latest['KDJ_K']
        if kdj_k > 80:
            kdj_status = "超买"
        elif kdj_k < 20:
            kdj_status = "超卖"
        else:
            kdj_status = "正常"

        # RSI分析
        rsi6 = latest.get('RSI6', 50)
        if rsi6 > 70:
            rsi_status = "超买"
        elif rsi6 < 30:
            rsi_status = "超卖"
        else:
            rsi_status = "正常"

        # BOLL分析
        boll_upper = latest['BOLL_UPPER']
        boll_lower = latest['BOLL_LOWER']
        if close > boll_upper:
            boll_position = "上轨上方"
        elif close < boll_lower:
            boll_position = "下轨下方"
        else:
            boll_position = "轨道内"

        return {
            'trend': trend,
            'macd_signal': macd_signal,
            'macd_status': macd_status,
            'kdj_status': kdj_status,
            'rsi_status': rsi_status,
            'boll_position': boll_position
        }

    @staticmethod
    def calculate_support_resistance(df: pd.DataFrame, lookback: int = 20) -> Dict:
        """
        计算支撑位和压力位

        :param df: 包含OHLC数据的DataFrame
        :param lookback: 回看周期
        :return: 包含支撑位和压力位的字典
        """
        recent = df.tail(lookback)

        # 使用最近的高低点作为压力和支撑
        highs = recent['最高'].nlargest(3).tolist()
        lows = recent['最低'].nsmallest(3).tolist()

        # MA线作为动态支撑压力
        latest = df.iloc[-1]
        ma_values = [latest.get('MA5', 0), latest.get('MA10', 0),
                     latest.get('MA20', 0), latest.get('MA60', 0)]

        close = latest['收盘']
        resistances = sorted([h for h in highs if h > close])[:3]
        supports = sorted([l for l in lows if l < close], reverse=True)[:3]

        # 补充均线支撑压力
        resistances.extend([ma for ma in ma_values if ma > close])
        supports.extend([ma for ma in ma_values if 0 < ma < close])

        resistances = sorted(set(resistances))[:3]
        supports = sorted(set(supports), reverse=True)[:3]

        return {
            'resistances': resistances if resistances else [close * 1.05],
            'supports': supports if supports else [close * 0.95]
        }
