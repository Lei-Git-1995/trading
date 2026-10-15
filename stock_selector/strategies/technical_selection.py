#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固定指标与周期形态选股策略。

本模块只负责历史 K 线指标计算和策略判断，数据获取由 stock_selector 的 provider 层负责。
"""

from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from stock_selector.config import SELECTION_CONFIG
from stock_selector.indicators.pattern_recognition import detect_pattern
from stock_selector.utils.logger import get_logger

logger = get_logger(__name__)


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
    ma20 = _num(row.get('MA20'))
    slope = (ma20 - _num(df.iloc[-6].get('MA20'))) / ma20 * 100 if ma20 else 0
    close = _num(row.get('收盘'))
    ok = (_num(row.get('MA5')) > _num(row.get('MA10'))
          and close >= ma20 * 0.98 and slope >= -0.2)
    return _result(ok, 'MA5高于MA10且收盘接近MA20' if ok else '短期均线或MA20位置未满足', ma20_slope_pct=slope)


def _macd_cross(df):
    if len(df) < 3:
        return _result(False, '历史数据不足3个交易日')
    dif, dea = df['MACD_DIF'], df['MACD_DEA']
    cross = any(dif.iloc[i] > dea.iloc[i] and dif.iloc[i - 1] <= dea.iloc[i - 1]
                for i in range(max(1, len(df) - 5), len(df)))
    row = df.iloc[-1]
    bar_rising = _num(row.get('MACD_BAR')) > _num(df.iloc[-2].get('MACD_BAR'))
    ok = cross and (_num(row.get('MACD_BAR')) > 0 or bar_rising) and _num(row.get('收盘')) >= _num(row.get('MA10')) * 0.98
    return _result(ok, '近5日MACD金叉或红柱改善' if ok else 'MACD条件未满足', macd_bar=_num(row.get('MACD_BAR')))


def _rsi_rebound(df):
    if len(df) < 15:
        return _result(False, '历史数据不足15个交易日')
    row, prev = df.iloc[-1], df.iloc[-2]
    rsi6, rsi12 = _num(row.get('RSI6')), _num(row.get('RSI12'))
    ok = 25 <= rsi6 <= 75 and rsi6 >= _num(prev.get('RSI6')) and rsi12 >= 35
    return _result(ok, 'RSI6处于可接受区间并企稳' if ok else 'RSI反弹条件未满足', rsi6=rsi6, rsi12=rsi12)


def _boll_breakout(df):
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    row = df.iloc[-1]
    ratio = _num(row.get('VOLUME_RATIO'))
    upper = _num(row.get('BOLL_UPPER'))
    ok = _num(row.get('收盘')) >= upper * 0.99 and ratio >= 0.8
    return _result(ok, '接近或突破布林上轨且量比不低于0.8' if ok else '布林位置或量比条件未满足', volume_ratio=ratio)


def _volume_breakout(df):
    lookback = SELECTION_CONFIG['breakout_lookback']
    if len(df) < lookback + 1:
        return _result(False, '历史数据不足突破观察周期')
    row = df.iloc[-1]
    previous_high = _num(df['最高'].iloc[-lookback - 1:-1].max())
    ratio = _num(row.get('VOLUME_RATIO'))
    ok = (_num(row.get('收盘')) >= previous_high * 0.99 and _num(row.get('涨跌幅')) >= -1.0
          and ratio >= SELECTION_CONFIG['volume_surge_ratio'])
    return _result(ok, '接近突破近15日高点且量比达标' if ok else '突破位置或量比条件未满足', previous_high=previous_high, volume_ratio=ratio)


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
    ok = best_run >= required and _num(row.get('收盘')) >= _num(row.get('MA20')) * 0.97
    return _result(ok, '近%d日连续%d天温和上涨' % (window, required) if ok else '连续温和上涨或趋势过滤未满足', best_consecutive=best_run)


def _sideways_then_up_3(df):
    """横盘整理后，最新连续 N 个交易日收盘价逐日上涨。

    横盘段与上涨确认段分开，避免把上涨本身算进横盘振幅。
    range 使用最高/最低价，slope 使用首尾收盘价，volatility 使用日收益标准差。
    """
    window = int(SELECTION_CONFIG['sideways_window'])
    up_days = int(SELECTION_CONFIG['sideways_up_days'])
    max_range = float(SELECTION_CONFIG['sideways_max_range_pct'])
    max_slope = float(SELECTION_CONFIG['sideways_max_slope_pct'])
    max_vol = float(SELECTION_CONFIG['sideways_max_volatility_pct'])
    if len(df) < window + up_days:
        return _result(False, '历史数据不足横盘和上涨确认窗口', sideways_days=window, up_days=up_days)

    prices = pd.to_numeric(df['收盘'], errors='coerce')
    segment = df.iloc[-(window + up_days):-up_days]
    closes = pd.to_numeric(segment['收盘'], errors='coerce').dropna()
    highs = pd.to_numeric(segment['最高'], errors='coerce').dropna()
    lows = pd.to_numeric(segment['最低'], errors='coerce').dropna()
    if len(closes) < window or highs.empty or lows.empty or closes.iloc[0] <= 0:
        return _result(False, '横盘窗口存在无效价格数据')

    range_pct = (highs.max() - lows.min()) / closes.mean() * 100
    slope_pct = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
    volatility_pct = closes.pct_change().dropna().std() * 100
    recent = prices.tail(up_days)
    up_days_count = int((recent.diff().iloc[1:] > 0).sum())
    consecutive_up = up_days_count >= 2
    ok = (consecutive_up and range_pct <= max_range and abs(slope_pct) <= max_slope
          and volatility_pct <= max_vol)
    return _result(
        ok,
        '横盘后最新%d日收盘连续上涨' % up_days if ok else '横盘幅度、波动率或连续上涨条件未满足',
        sideways_range_pct=range_pct, sideways_slope_pct=slope_pct,
        sideways_volatility_pct=volatility_pct, recent_up_days=up_days_count,
    )


def _classic_pattern(df):
    """识别适合作为候选信号的双底、三角形或矩形整理。"""
    matches = {}
    for pattern in ('double_bottom', 'triangle', 'rectangle'):
        result = detect_pattern(df, pattern, order=2, min_separation=4)
        matches[pattern] = result['matched']
    matched = any(matches.values())
    return _result(matched, '检测到经典整理/反转形态' if matched else '未检测到符合条件的经典形态', patterns=matches)


def _pullback_rebound(df):
    if len(df) < 20:
        return _result(False, '历史数据不足20个交易日')
    recent = df.tail(10)
    row = df.iloc[-1]
    high = _num(recent['最高'].iloc[:-2].max())
    low = _num(recent['最低'].iloc[:-2].min())
    drawdown = (high - low) / high * 100 if high else 0
    ok = drawdown >= 2 and _num(row.get('收盘')) >= _num(row.get('MA5')) * 0.99 and _num(row.get('涨跌幅')) >= -0.5
    return _result(ok, '回撤后站回MA5并反弹' if ok else '回撤或反弹条件未满足', drawdown=drawdown)


def _multi_factor(df):
    checks = {'趋势': _ma_trend(df)['matched'], 'MACD': _macd_cross(df)['matched'],
              '量价突破': _volume_breakout(df)['matched'], 'RSI反弹': _rsi_rebound(df)['matched'],
              '布林突破': _boll_breakout(df)['matched']}
    score = sum(1 for value in checks.values() if value)
    return _result(score >= 2, '五项因子至少满足两项' if score >= 2 else '满足因子少于两项', score=score, factors=checks)


STRATEGIES = [
    {'id': 'ma_trend', 'name': '均线趋势', 'description': 'MA5高于MA10，收盘接近MA20且MA20走平或向上', 'func': _ma_trend},
    {'id': 'macd_cross', 'name': 'MACD金叉', 'description': '近5日MACD金叉或红柱改善，收盘接近MA10', 'func': _macd_cross},
    {'id': 'rsi_rebound', 'name': 'RSI回升', 'description': 'RSI6处于25-75并企稳，RSI12不弱', 'func': _rsi_rebound},
    {'id': 'boll_breakout', 'name': '布林上轨突破', 'description': '收盘接近布林上轨，量比至少0.8', 'func': _boll_breakout},
    {'id': 'volume_breakout', 'name': '放量突破', 'description': '收盘接近近15日高点，量比至少1.0', 'func': _volume_breakout},
    {'id': 'accumulation_3of10', 'name': '温和连续上涨吸筹', 'description': '近10日连续上涨，每天涨幅温和', 'func': _accumulation},
    {'id': 'sideways_then_up_3', 'name': '横盘后转强', 'description': '先横盘整理，最近3日至少2日收盘上涨', 'func': _sideways_then_up_3},
    {'id': 'classic_pattern', 'name': '经典价格形态', 'description': '识别双底、三角形或矩形整理候选', 'func': _classic_pattern},
    {'id': 'pullback_rebound', 'name': '回撤后反弹', 'description': '近10日回撤至少2%，随后回到MA5附近企稳', 'func': _pullback_rebound},
    {'id': 'multi_factor', 'name': '多因子综合', 'description': '趋势、MACD、量价、RSI、布林五项至少满足两项', 'func': _multi_factor},
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
        result.setdefault('metrics', {})
        if 'VOLUME_RATIO' in prepared.columns and len(prepared):
            result['metrics'].setdefault('volume_ratio', _num(prepared['VOLUME_RATIO'].iloc[-1]))
        result['strategy_id'] = strategy_id
        result['latest_date'] = prepared.iloc[-1].get('日期') if len(prepared) else None
        return result

    @classmethod
    def screen(cls, stock_list: pd.DataFrame, provider, strategy_id: str, days: int = 150,
               limit: int = 0, cache=None, workers: int = 4):
        return cls.screen_many(stock_list, provider, [strategy_id], days=days,
                               limit=limit, cache=cache, workers=workers)[strategy_id]

    @classmethod
    def screen_many(cls, stock_list: pd.DataFrame, provider, strategy_ids: List[str],
                    days: int = 150, limit: int = 0, cache=None, workers: int = 4):
        """每只股票只获取一次历史 K 线，再执行所有指定策略。"""
        for strategy_id in strategy_ids:
            if strategy_id not in STRATEGY_MAP:
                raise ValueError('未知策略: %s' % strategy_id)

        results = {strategy_id: [] for strategy_id in strategy_ids}
        stocks = stock_list if not limit else stock_list.head(limit)

        def fetch(item):
            _, stock = item
            code = str(stock.get('code', '')).zfill(6)
            try:
                hist = cache.get(code) if cache is not None else None
                if hist is None:
                    hist = provider.get_stock_history(code, days=days)
                    if cache is not None:
                        cache.set(code, hist)
                if hist is None or hist.empty:
                    return []
                matched = []
                for strategy_id in strategy_ids:
                    result = cls.evaluate(hist, strategy_id)
                    if result['matched']:
                        latest = hist.iloc[-1]
                        # 成交额（亿元）：K线成交额原始单位为元
                        amt_raw = latest.get('成交额')
                        try:
                            amount_yi = float(amt_raw) / 1e8 if pd.notna(amt_raw) else None
                        except (TypeError, ValueError):
                            amount_yi = None
                        matched.append((strategy_id, {
                            'code': code, 'name': stock.get('name', code),
                            'price': stock.get('price'), 'change_pct': stock.get('change_pct'),
                            'turnover': stock.get('turnover'), 'volume': stock.get('volume'),
                            'amount': amount_yi,
                            'outer_ratio': stock.get('outer_ratio'),
                            'sector': stock.get('sector', ''), 'latest_date': result['latest_date'],
                            'reason': result['reason'], 'metrics': dict(result.get('metrics') or {}),
                        }))
                return matched
            except Exception:
                return []

        items = list(stocks.iterrows())
        worker_count = max(1, min(int(workers or 1), 12))
        total = len(items)
        logger.info(f'  开始获取/分析 {total} 只股票的K线（并发 {worker_count}）…')
        if worker_count == 1 or len(items) < 2:
            fetched = []
            for idx, item in enumerate(items, 1):
                fetched.append(fetch(item))
                if idx % 20 == 0:
                    logger.info(f'  技术形态分析进度: {idx}/{total}')
        else:
            fetched = []
            done = 0
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix='technical-kline') as pool:
                futures = [pool.submit(fetch, item) for item in items]
                for future in as_completed(futures):
                    fetched.append(future.result())
                    done += 1
                    if done % 20 == 0:
                        logger.info(f'  技术形态分析进度: {done}/{total}')
        logger.info(f'  技术形态分析完成: {total} 只')
        for matches in fetched:
            for strategy_id, row in matches:
                results[strategy_id].append(row)
        return results
