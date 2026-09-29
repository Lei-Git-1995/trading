#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固定指标与周期形态选股策略。

本模块只负责历史 K 线指标计算和策略判断，数据获取由 stock_selector 的 provider 层负责。
"""

from typing import Dict, List

import numpy as np
import pandas as pd

from stock_selector.config import SELECTION_CONFIG


def _num(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """在标准 K 线数据上计算选股指标。"""
    out = df.copy()
    if '日期' in out.columns:
        out['日期'] = pd.to_datetime(out['日期'], errors='coerce')
        out = out.sort_values('日期')
    for col in ['开盘', '收盘', '最高', '最低', '成交量', '成交额', '涨跌幅']:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors='coerce')
    if '涨跌幅' not in out.columns:
        out['涨跌幅'] = out['收盘'].pct_change() * 100
    out['涨跌幅'] = out['涨跌幅'].fillna(0.0)

    for period in [5, 10, 20, 60, 120]:
        out['MA%s' % period] = out['收盘'].rolling(period).mean()
    for period in [12, 26, 50]:
        out['EMA%s' % period] = out['收盘'].ewm(span=period, adjust=False).mean()

    ema12 = out['收盘'].ewm(span=12, adjust=False).mean()
    ema26 = out['收盘'].ewm(span=26, adjust=False).mean()
    out['MACD_DIF'] = ema12 - ema26
    out['MACD_DEA'] = out['MACD_DIF'].ewm(span=9, adjust=False).mean()
    out['MACD_BAR'] = (out['MACD_DIF'] - out['MACD_DEA']) * 2

    low = out['最低'].rolling(9, min_periods=1).min()
    high = out['最高'].rolling(9, min_periods=1).max()
    rsv = ((out['收盘'] - low) / (high - low).replace(0, np.nan) * 100).fillna(0)
    out['KDJ_K'] = rsv.ewm(com=2, adjust=False).mean()
    out['KDJ_D'] = out['KDJ_K'].ewm(com=2, adjust=False).mean()
    out['KDJ_J'] = 3 * out['KDJ_K'] - 2 * out['KDJ_D']

    delta = out['收盘'].diff()
    for period in [6, 12, 24]:
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        out['RSI%s' % period] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    mid = out['收盘'].rolling(20).mean()
    std = out['收盘'].rolling(20).std()
    out['BOLL_MID'] = mid
    out['BOLL_UPPER'] = mid + 2 * std
    out['BOLL_LOWER'] = mid - 2 * std
    out['BOLL_WIDTH'] = (out['BOLL_UPPER'] - out['BOLL_LOWER']) / mid * 100

    out['VOL_MA5'] = out['成交量'].rolling(5, min_periods=1).mean()
    out['VOL_MA20'] = out['成交量'].rolling(20, min_periods=1).mean()
    out['VOLUME_RATIO'] = out['成交量'] / out['VOL_MA20'].replace(0, np.nan)

    previous_close = out['收盘'].shift(1)
    tr = pd.concat([out['最高'] - out['最低'], (out['最高'] - previous_close).abs(),
                    (out['最低'] - previous_close).abs()], axis=1).max(axis=1)
    out['ATR14'] = tr.rolling(14, min_periods=1).mean()
    direction = out['收盘'].diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    out['OBV'] = (direction * out['成交量']).cumsum()
    out['OBV_MA20'] = out['OBV'].rolling(20, min_periods=1).mean()
    return out


def _result(matched, reason, **metrics):
    return {'matched': bool(matched), 'reason': reason, 'metrics': metrics}


def _ma_trend(df):
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    row = df.iloc[-1]
    slope = _num(row.get('MA20')) - _num(df.iloc[-6].get('MA20'))
    ok = (_num(row.get('MA5')) > _num(row.get('MA10')) > _num(row.get('MA20'))
          and _num(row.get('收盘')) > _num(row.get('MA20')) and slope > 0)
    return _result(ok, 'MA5>MA10>MA20且MA20向上' if ok else '均线排列或趋势斜率不满足', ma20_slope=slope)


def _macd_cross(df):
    if len(df) < 3:
        return _result(False, '历史数据不足3个交易日')
    dif, dea = df['MACD_DIF'], df['MACD_DEA']
    cross = any(dif.iloc[i] > dea.iloc[i] and dif.iloc[i - 1] <= dea.iloc[i - 1]
                for i in range(max(1, len(df) - 3), len(df)))
    row = df.iloc[-1]
    ok = cross and _num(row.get('MACD_BAR')) > 0 and _num(row.get('收盘')) > _num(row.get('MA20'))
    return _result(ok, '近3日MACD金叉且红柱' if ok else 'MACD条件未满足', macd_bar=_num(row.get('MACD_BAR')))


def _rsi_rebound(df):
    if len(df) < 15:
        return _result(False, '历史数据不足15个交易日')
    row, prev = df.iloc[-1], df.iloc[-2]
    rsi6, rsi12 = _num(row.get('RSI6')), _num(row.get('RSI12'))
    ok = 35 <= rsi6 <= 65 and rsi6 > _num(prev.get('RSI6')) and rsi12 >= 45
    return _result(ok, 'RSI6中低位回升且RSI12不弱' if ok else 'RSI反弹条件未满足', rsi6=rsi6, rsi12=rsi12)


def _boll_breakout(df):
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    row = df.iloc[-1]
    ratio = _num(row.get('VOLUME_RATIO'))
    ok = _num(row.get('收盘')) > _num(row.get('BOLL_UPPER')) and ratio >= 1.2
    return _result(ok, '突破布林上轨且量比不低于1.2' if ok else '布林突破或量比条件未满足', volume_ratio=ratio)


def _volume_breakout(df):
    lookback = SELECTION_CONFIG['breakout_lookback']
    if len(df) < lookback + 1:
        return _result(False, '历史数据不足突破观察周期')
    row = df.iloc[-1]
    previous_high = _num(df['最高'].iloc[-lookback - 1:-1].max())
    ratio = _num(row.get('VOLUME_RATIO'))
    ok = (_num(row.get('收盘')) > previous_high and _num(row.get('涨跌幅')) > 0
          and ratio >= SELECTION_CONFIG['volume_surge_ratio'])
    return _result(ok, '放量突破近20日高点' if ok else '突破或放量条件未满足', previous_high=previous_high, volume_ratio=ratio)


def _accumulation(df):
    window = SELECTION_CONFIG['accumulation_window']
    required = SELECTION_CONFIG['accumulation_consecutive_days']
    minimum = SELECTION_CONFIG['accumulation_daily_gain_min']
    maximum = SELECTION_CONFIG['accumulation_daily_gain_max']
    if len(df) < window + 1:
        return _result(False, '历史数据不足周期观察窗口')
    best_run = current = 0
    for gain in df.tail(window)['涨跌幅'].tolist():
        value = _num(gain)
        if minimum - 1e-8 <= value <= maximum + 1e-8:
            current += 1
            best_run = max(best_run, current)
        else:
            current = 0
    row = df.iloc[-1]
    ok = best_run >= required and _num(row.get('收盘')) >= _num(row.get('MA20'))
    return _result(ok, '近10日连续3天上涨且单日1%-3%' if ok else '连续温和上涨或趋势过滤未满足', best_consecutive=best_run)


def _pullback_rebound(df):
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    recent = df.tail(10)
    row = df.iloc[-1]
    high = _num(recent['最高'].iloc[:-2].max())
    low = _num(recent['最低'].iloc[:-2].min())
    drawdown = (high - low) / high * 100 if high else 0
    ok = drawdown >= 5 and _num(row.get('收盘')) > _num(row.get('MA5')) and _num(row.get('涨跌幅')) > 0
    return _result(ok, '回撤后站回MA5并反弹' if ok else '回撤或反弹条件未满足', drawdown=drawdown)


def _multi_factor(df):
    checks = {'趋势': _ma_trend(df)['matched'], 'MACD': _macd_cross(df)['matched'],
              '量价突破': _volume_breakout(df)['matched'], 'RSI反弹': _rsi_rebound(df)['matched'],
              '布林突破': _boll_breakout(df)['matched']}
    score = sum(1 for value in checks.values() if value)
    return _result(score >= 3, '五项因子至少满足三项' if score >= 3 else '满足因子少于三项', score=score, factors=checks)


STRATEGIES = [
    {'id': 'ma_trend', 'name': '均线多头趋势', 'description': 'MA5>MA10>MA20，收盘在MA20上方且MA20向上', 'func': _ma_trend},
    {'id': 'macd_cross', 'name': 'MACD金叉', 'description': '近3日形成金叉、红柱转强，收盘在MA20上方', 'func': _macd_cross},
    {'id': 'rsi_rebound', 'name': 'RSI回升', 'description': 'RSI6处于35-65并回升，RSI12不弱', 'func': _rsi_rebound},
    {'id': 'boll_breakout', 'name': '布林上轨突破', 'description': '收盘突破布林上轨，量比至少1.2', 'func': _boll_breakout},
    {'id': 'volume_breakout', 'name': '放量突破', 'description': '收盘突破近20日高点，量比至少1.5', 'func': _volume_breakout},
    {'id': 'accumulation_3of10', 'name': '温和连续上涨吸筹', 'description': '近10日连续3天上涨，每天涨幅1%-3%', 'func': _accumulation},
    {'id': 'pullback_rebound', 'name': '回撤后反弹', 'description': '近10日先回撤至少5%，随后站回MA5反弹', 'func': _pullback_rebound},
    {'id': 'multi_factor', 'name': '多因子综合', 'description': '趋势、MACD、量价、RSI、布林五项至少满足三项', 'func': _multi_factor},
]
STRATEGY_MAP = dict((item['id'], item) for item in STRATEGIES)


class TechnicalSelector:
    """对单只 K 线或股票池执行技术形态策略。"""

    @staticmethod
    def evaluate(hist: pd.DataFrame, strategy_id: str) -> Dict:
        if strategy_id not in STRATEGY_MAP:
            raise ValueError('未知策略: %s' % strategy_id)
        prepared = calculate_indicators(hist)
        result = STRATEGY_MAP[strategy_id]['func'](prepared)
        result['strategy_id'] = strategy_id
        result['latest_date'] = prepared.iloc[-1].get('日期') if len(prepared) else None
        return result

    @classmethod
    def screen(cls, stock_list: pd.DataFrame, provider, strategy_id: str, days: int = 150, limit: int = 0):
        rows = []
        stocks = stock_list if not limit else stock_list.head(limit)
        for _, stock in stocks.iterrows():
            code = str(stock.get('code', '')).zfill(6)
            try:
                hist = provider.get_stock_history(code, days=days)
                if hist is None or hist.empty:
                    continue
                result = cls.evaluate(hist, strategy_id)
                if result['matched']:
                    rows.append({'code': code, 'name': stock.get('name', code),
                                 'price': stock.get('price'), 'change_pct': stock.get('change_pct'),
                                 'sector': stock.get('sector', ''), 'latest_date': result['latest_date'],
                                 'reason': result['reason'], 'metrics': result['metrics']})
            except Exception:
                continue
        return rows
