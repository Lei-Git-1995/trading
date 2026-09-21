"""短线选股策略：整合行情、指标与评分"""
import time

import numpy as np
import pandas as pd

from stock_selector.data.cache import KlineCache
from stock_selector.data.eastmoney_client import EastMoneyClient
from stock_selector.indicators.kdj import kdj_k
from stock_selector.indicators.rsi import rsi6
from stock_selector.indicators.volume import check_volume_boost
from stock_selector.utils.logger import get_logger

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

logger = get_logger(__name__)


class ShortTermSelector:
    """
    短线选股流程：
      1. 快筛（换手率 / 涨幅 / 成交 / 内外盘）
      2. 深度分析（历史K线 + KDJ/RSI + 量能验证）
      3. 综合评分排序
      4. 每个板块数量限制
    """

    def __init__(self, config, client: EastMoneyClient = None, cache: KlineCache = None):
        self.config = config
        self.client = client or EastMoneyClient()
        self.cache = cache  # None 表示禁用缓存（--no-cache）

    # ---------------- 第一步：快筛 ----------------

    def quick_screen(self, stock_list: pd.DataFrame) -> list:
        logger.info('\n[2/4] 开始筛选符合条件的股票...')
        c = self.config
        logger.info(f'  筛选条件:')
        logger.info(f'    - 换手率 > {c.turnover_min}%')
        logger.info(f'    - 涨幅 {c.change_min}% ~ {c.change_max}%')
        if c.check_outer_inner:
            logger.info(f'    - 成交量 > 0,外盘 > 内盘')
        else:
            logger.info(f'    - 成交量 > 0')
        if c.filter_cyb or c.filter_kcb:
            filters = []
            if c.filter_cyb:
                filters.append('创业板(3开头)')
            if c.filter_kcb:
                filters.append('科创板(688开头)')
            logger.info(f'    - 过滤: {", ".join(filters)}')

        candidates = []
        for _, s in stock_list.iterrows():
            code = s['code']

            # 板块过滤
            if c.filter_cyb and code.startswith('3'):
                continue
            if c.filter_kcb and code.startswith('688'):
                continue

            if not (c.change_min <= s['change_pct'] <= c.change_max):
                continue
            # 换手率缺失(如新浪列表)时跳过换手过滤，但提示
            if pd.notna(s['turnover']) and s['turnover'] <= c.turnover_min:
                continue
            if s['volume'] <= 0:
                continue
            # 外盘/内盘缺失(如腾讯/新浪)时不检查
            if c.check_outer_inner and pd.notna(s['outer_vol']) and pd.notna(s['inner_vol']):
                if s['outer_vol'] <= s['inner_vol']:
                    continue

            candidates.append(s.to_dict())

        logger.info(f'  初步筛选: {len(candidates)} 只')
        return candidates

    # ---------------- 第二步：深度分析 ----------------

    def deep_analysis(self, candidates: list) -> list:
        logger.info(f'\n[3/4] 深度分析（历史K线 + 技术指标 + 量能验证）...')
        c = self.config
        qualified = []
        total = len(candidates)

        # 使用 tqdm 进度条（如果可用）
        if HAS_TQDM:
            iterator = tqdm(candidates, desc='  分析进度', unit='只', ncols=80)
        else:
            iterator = candidates

        for idx, cand in enumerate(iterator, 1):
            # 无 tqdm 时显示进度
            if not HAS_TQDM and idx % 10 == 0:
                logger.info(f'  进度: {idx}/{total}')

            code = cand['code']
            hist = self.cache.get(code) if self.cache is not None else None
            if hist is None:
                hist = self.client.get_stock_history(code, days=c.history_days)
                if self.cache is not None:
                    self.cache.set(code, hist)
                time.sleep(c.request_sleep)

            if hist is None or len(hist) < 3:
                continue

            ind = self._compute_indicators(hist)
            if ind is None:
                continue

            # 量能放量验证
            vol_ratio, ok = check_volume_boost(ind['成交量'], threshold=c.volume_ratio)
            if not ok:
                continue

            # 技术指标不超买（--no-kdj / --no-rsi 可关闭对应检查）
            kdj_val = ind['KDJ_K'].iloc[-1]
            rsi_val = ind['RSI6'].iloc[-1]
            if c.check_kdj and pd.notna(kdj_val) and kdj_val >= 80:
                continue
            if c.check_rsi and pd.notna(rsi_val) and rsi_val >= 70:
                continue

            # 检查是否炸板(不过滤,只标记)
            is_failed_limit = self._is_failed_limit_up(hist)

            recent_3day = float(hist['涨跌幅'].iloc[-3:].sum())

            qualified.append({
                **cand,
                'volume_ratio': vol_ratio,
                'kdj_k': float(kdj_val) if pd.notna(kdj_val) else None,
                'rsi6': float(rsi_val) if pd.notna(rsi_val) else None,
                'recent_3day_change': recent_3day,
                'is_failed_limit': is_failed_limit,  # 炸板标记
                'hist_data': ind,
            })

        logger.info(f'  深度分析完成: {len(qualified)} 只通过')
        return qualified

    def _compute_indicators(self, hist: pd.DataFrame) -> pd.DataFrame:
        """在历史K线上挂 KDJ_K / RSI6 / 成交量列"""
        try:
            df = hist.copy()
            df['KDJ_K'] = kdj_k(df['最高'], df['最低'], df['收盘'])
            df['RSI6'] = rsi6(df['收盘'])
            return df
        except Exception:
            return None

    def _is_failed_limit_up(self, hist: pd.DataFrame) -> bool:
        """
        判断今日是否炸板(涨停后打开)
        炸板特征:
        1. 今日最高价触及涨停价(昨收*1.1或1.2)
        2. 今日收盘价明显低于最高价
        3. 振幅较大,说明盘中波动剧烈
        """
        if len(hist) < 2:
            return False

        today = hist.iloc[-1]
        yesterday_close = hist.iloc[-2]['收盘']

        # 计算涨停价(主板10%,创业板/科创板20%)
        # 简化判断:股票代码3/6/0开头按10%,其他按20%
        limit_up_pct = 0.10  # 默认10%

        limit_up_price = yesterday_close * (1 + limit_up_pct)

        # 判断是否触及涨停
        # 最高价达到涨停价的98%以上视为触及涨停
        touched_limit = today['最高'] >= limit_up_price * 0.98

        if not touched_limit:
            return False

        # 判断是否炸板:收盘价明显低于最高价
        # 收盘价比最高价低3%以上,且振幅>5%
        price_drop_pct = (today['最高'] - today['收盘']) / today['最高'] * 100
        amplitude = today['振幅']

        is_failed = price_drop_pct >= 3.0 and amplitude >= 5.0

        return is_failed

    # ---------------- 第三步：评分 ----------------

    def rank(self, qualified: list) -> list:
        logger.info('\n[4/4] 综合评分（满分80）...')
        for s in qualified:
            score = 0

            # 涨幅（1.5-2.5% 最佳，10分）
            chg = s['change_pct']
            if 1.5 <= chg <= 2.5:
                score += 10
            elif 1 <= chg < 1.5:
                score += 8
            elif 2.5 < chg <= 3:
                score += 7

            # 换手（15-25% 最佳，10分）
            to = s['turnover']
            if 15 <= to <= 25:
                score += 10
            elif 25 < to <= 35:
                score += 8
            elif to > 35:
                score += 5

            # 量能（1.5-3倍最佳，15分）
            vr = s['volume_ratio']
            if 1.5 <= vr <= 2:
                score += 15
            elif 2 < vr <= 3:
                score += 13
            elif vr > 3:
                score += 10

            # 外盘占比（越高越好，15分）
            orr = s['outer_ratio']
            if orr >= 65:
                score += 15
            elif orr >= 60:
                score += 13
            elif orr >= 55:
                score += 10
            elif orr >= 52:
                score += 7
            else:
                score += 5

            # KDJ（30-60最佳，10分）
            k = s['kdj_k']
            if k is not None:
                if 30 <= k <= 60:
                    score += 10
                elif 60 < k < 80:
                    score += 7
                elif k < 30:
                    score += 5

            # RSI（40-60最佳，10分）
            r = s['rsi6']
            if r is not None:
                if 40 <= r <= 60:
                    score += 10
                elif 60 < r < 70:
                    score += 7
                elif r < 40:
                    score += 8

            # 近3日涨幅（5-15%最佳，10分）
            c3 = s['recent_3day_change']
            if 5 <= c3 <= 15:
                score += 10
            elif 0 <= c3 < 5:
                score += 8
            elif 15 < c3 <= 25:
                score += 5

            s['score'] = score

        qualified.sort(key=lambda x: x['score'], reverse=True)
        logger.info(f'  评分完成，最高分: {qualified[0]["score"] if qualified else 0}/80')
        return qualified

    # ---------------- 第四步：板块限制 ----------------

    def limit_by_sector(self, qualified: list) -> list:
        c = self.config
        if c.top_per_sector <= 0:
            return qualified

        sector_map = {}
        for s in qualified:
            sector_map.setdefault(s['sector'], []).append(s)

        limited = []
        for sector, stocks in sector_map.items():
            limited.extend(stocks[:c.top_per_sector])
            if len(stocks) > c.top_per_sector:
                logger.info(f'  {sector}: {len(stocks)}只 -> 取前{c.top_per_sector}只')

        limited.sort(key=lambda x: x['score'], reverse=True)
        return limited

    # ---------------- 全流程 ----------------

    def run(self, stock_list: pd.DataFrame) -> list:
        candidates = self.quick_screen(stock_list)
        if not candidates:
            return []
        results = self.deep_analysis(candidates)
        if not results:
            return []
        results = self.rank(results)
        results = self.limit_by_sector(results)
        return results