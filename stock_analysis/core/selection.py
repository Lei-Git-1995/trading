#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固定指标与周期形态选股策略。"""

from typing import Callable, Dict, List, Tuple

import pandas as pd

from ..config import SELECTION_CONFIG
from .indicators import TechnicalIndicators


def _num(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    """统一日期、数值类型并计算选股所需指标。"""
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
    return TechnicalIndicators.calculate_all(out)


def _result(matched: bool, reason: str, **metrics) -> Dict:
    return {'matched': bool(matched), 'reason': reason, 'metrics': metrics}


def _ma_trend(df: pd.DataFrame) -> Dict:
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    row = df.iloc[-1]
    ok = (_num(row.get('MA5')) > _num(row.get('MA10')) > _num(row.get('MA20'))
          and _num(row.get('收盘')) > _num(row.get('MA20')))
    slope = _num(row.get('MA20')) - _num(df.iloc[-6].get('MA20'))
    ok = ok and slope > 0
    return _result(ok, 'MA5>MA10>MA20且收盘价在MA20上方、MA20向上' if ok else '均线排列或趋势斜率不满足',
                   close=_num(row.get('收盘')), ma20=_num(row.get('MA20')), ma20_slope=slope)


def _macd_cross(df: pd.DataFrame) -> Dict:
    if len(df) < 3:
        return _result(False, '历史数据不足3个交易日')
    dif = df['MACD_DIF']
    dea = df['MACD_DEA']
    cross = (dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2])
    recent_cross = False
    for i in range(max(1, len(df) - 3), len(df)):
        recent_cross = recent_cross or (dif.iloc[i] > dea.iloc[i] and dif.iloc[i - 1] <= dea.iloc[i - 1])
    row = df.iloc[-1]
    ok = recent_cross and _num(row.get('MACD_BAR')) > 0 and _num(row.get('收盘')) > _num(row.get('MA20'))
    return _result(ok, '近3日MACD金叉且红柱、收盘在MA20上方' if ok else 'MACD金叉或趋势过滤未满足',
                   macd_bar=_num(row.get('MACD_BAR')), exact_cross=cross)


def _rsi_rebound(df: pd.DataFrame) -> Dict:
    if len(df) < 15:
        return _result(False, '历史数据不足15个交易日')
    row, prev = df.iloc[-1], df.iloc[-2]
    rsi6, rsi12 = _num(row.get('RSI6')), _num(row.get('RSI12'))
    ok = 35 <= rsi6 <= 65 and rsi6 > _num(prev.get('RSI6')) and rsi12 >= 45
    return _result(ok, 'RSI6从中低位回升且RSI12不弱' if ok else 'RSI反弹条件未满足', rsi6=rsi6, rsi12=rsi12)


def _boll_breakout(df: pd.DataFrame) -> Dict:
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    row = df.iloc[-1]
    ratio = _num(row.get('VOLUME_RATIO'), 0)
    ok = _num(row.get('收盘')) > _num(row.get('BOLL_UPPER')) and ratio >= 1.2
    return _result(ok, '收盘突破布林上轨且量比不低于1.2' if ok else '布林突破或成交量条件未满足', volume_ratio=ratio)


def _volume_breakout(df: pd.DataFrame) -> Dict:
    lookback = SELECTION_CONFIG['breakout_lookback']
    if len(df) < lookback + 1:
        return _result(False, '历史数据不足突破观察周期')
    row = df.iloc[-1]
    previous_high = _num(df['最高'].iloc[-lookback-1:-1].max())
    ratio = _num(row.get('VOLUME_RATIO'), 0)
    ok = (_num(row.get('收盘')) > previous_high
          and _num(row.get('涨跌幅')) > 0
          and ratio >= SELECTION_CONFIG['volume_surge_ratio'])
    return _result(ok, '放量突破近20日高点' if ok else '突破、涨幅或放量条件未满足',
                   previous_high=previous_high, volume_ratio=ratio)


def _accumulation(df: pd.DataFrame) -> Dict:
    window = SELECTION_CONFIG['accumulation_window']
    required = SELECTION_CONFIG['accumulation_consecutive_days']
    min_gain = SELECTION_CONFIG['accumulation_daily_gain_min']
    max_gain = SELECTION_CONFIG['accumulation_daily_gain_max']
    if len(df) < window + 1:
        return _result(False, '历史数据不足周期观察窗口')
    recent = df.tail(window).reset_index(drop=True)
    gains = recent['涨跌幅'].tolist()
    best_run = 0
    current = 0
    for gain in gains:
        # 百分比经过浮点计算后可能出现 0.999999999，边界允许极小误差。
        value = _num(gain)
        if min_gain - 1e-8 <= value <= max_gain + 1e-8:
            current += 1
            best_run = max(best_run, current)
        else:
            current = 0
    row = recent.iloc[-1]
    ok = best_run >= required and _num(row.get('收盘')) >= _num(row.get('MA20'))
    return _result(ok, '近10日出现连续3天、单日上涨1%-3%且价格在MA20上方' if ok else '连续温和上涨或趋势过滤未满足',
                   best_consecutive=best_run, latest_gain=_num(row.get('涨跌幅')))


def _pullback_rebound(df: pd.DataFrame) -> Dict:
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    recent = df.tail(10)
    row = df.iloc[-1]
    prior_high = _num(recent['最高'].iloc[:-2].max())
    drawdown = (prior_high - _num(recent['最低'].iloc[:-2].min())) / prior_high * 100 if prior_high else 0
    ok = (drawdown >= 5 and _num(row.get('收盘')) > _num(row.get('MA5'))
          and _num(row.get('涨跌幅')) > 0 and _num(row.get('VOLUME_RATIO')) >= 1.0)
    return _result(ok, '回撤后重新站上MA5且量价修复' if ok else '回撤、反弹或量价条件未满足', drawdown=drawdown)


def _multi_factor(df: pd.DataFrame) -> Dict:
    checks = {
        '趋势': _ma_trend(df)['matched'],
        'MACD': _macd_cross(df)['matched'],
        '量价突破': _volume_breakout(df)['matched'],
        'RSI反弹': _rsi_rebound(df)['matched'],
        '布林突破': _boll_breakout(df)['matched'],
    }
    score = sum(1 for value in checks.values() if value)
    ok = score >= 3
    return _result(ok, '五项因子中至少满足三项' if ok else '满足的因子少于三项', score=score, factors=checks)


STRATEGIES = [
    {'id': 'ma_trend', 'name': '均线多头趋势', 'description': 'MA5>MA10>MA20，收盘在MA20上方且MA20向上', 'func': _ma_trend},
    {'id': 'macd_cross', 'name': 'MACD金叉', 'description': '近3日形成金叉、红柱转强，且收盘在MA20上方', 'func': _macd_cross},
    {'id': 'rsi_rebound', 'name': 'RSI回升', 'description': 'RSI6处于35-65并回升，RSI12不弱', 'func': _rsi_rebound},
    {'id': 'boll_breakout', 'name': '布林上轨突破', 'description': '收盘突破布林上轨，同时量比至少1.2', 'func': _boll_breakout},
    {'id': 'volume_breakout', 'name': '放量突破', 'description': '收盘突破近20日高点，涨幅为正且量比至少1.5', 'func': _volume_breakout},
    {'id': 'accumulation_3of10', 'name': '温和连续上涨吸筹', 'description': '近10日内连续3天上涨，每天涨幅1%-3%，且价格在MA20上方', 'func': _accumulation},
    {'id': 'pullback_rebound', 'name': '回撤后反弹', 'description': '近10日先有至少5%回撤，随后站回MA5并放量反弹', 'func': _pullback_rebound},
    {'id': 'multi_factor', 'name': '多因子综合', 'description': '趋势、MACD、量价、RSI、布林五项中至少满足三项', 'func': _multi_factor},
]

STRATEGY_MAP = dict((item['id'], item) for item in STRATEGIES)


class StockSelector:
    """对单只股票或股票池执行注册的选股策略。"""

    @staticmethod
    def list_strategies() -> List[Dict]:
        return [dict((k, v) for k, v in item.items() if k != 'func') for item in STRATEGIES]

    @staticmethod
    def evaluate(df: pd.DataFrame, strategy_id: str) -> Dict:
        if strategy_id not in STRATEGY_MAP:
            raise ValueError('未知选股策略: %s' % strategy_id)
        prepared = _prepare(df)
        result = STRATEGY_MAP[strategy_id]['func'](prepared)
        result['strategy_id'] = strategy_id
        result['latest_date'] = prepared.iloc[-1].get('日期') if len(prepared) else None
        return result

    @classmethod
    def select(cls, universe: List[Tuple[str, str, pd.DataFrame]], strategy_id: str) -> pd.DataFrame:
        rows = []
        for code, name, df in universe:
            try:
                result = cls.evaluate(df, strategy_id)
                if result['matched']:
                    metrics = result.get('metrics', {})
                    rows.append({
                        '股票代码': code,
                        '股票名称': name or code,
                        '策略': STRATEGY_MAP[strategy_id]['name'],
                        '最新日期': result.get('latest_date'),
                        '说明': result.get('reason', ''),
                        '指标': metrics,
                    })
            except Exception as exc:
                rows.append({'股票代码': code, '股票名称': name or code, '策略': STRATEGY_MAP[strategy_id]['name'],
                             '最新日期': None, '说明': '数据处理失败: %s' % exc, '指标': {}, '错误': True})
        return pd.DataFrame(rows)
