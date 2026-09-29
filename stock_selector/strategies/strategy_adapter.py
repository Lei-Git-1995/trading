"""策略适配器：桥接新旧架构

让基于评分引擎的新策略能够在现有主程序中运行
"""
from typing import Dict, List, Optional
import pandas as pd
import yaml
from pathlib import Path

from stock_selector.strategies.scoring_engine import ScoringEngine, ScoringResult
from stock_selector.data.sector_client import SectorClient
from stock_selector.data.intraday_client import IntradayClient
from stock_selector.data.capital_flow_client import CapitalFlowClient
from stock_selector.indicators.advanced_indicators import (
    relative_strength,
    ma_position,
    consecutive_days,
    recent_change,
    breakout_detection,
    platform_detection,
    momentum_acceleration,
    volume_expansion,
    calculate_ma,
    check_ma_support
)
from stock_selector.utils.logger import get_logger

logger = get_logger(__name__)


class StrategyAdapter:
    """
    策略适配器

    功能:
    1. 加载 v2 格式的策略配置
    2. 增强股票数据（计算高级指标）
    3. 调用评分引擎
    4. 转换结果为旧格式（兼容现有报告系统）
    """

    def __init__(self, strategy_name: str, config_path: Optional[Path] = None):
        """
        Args:
            strategy_name: 策略名称（如 'ultra_short'）
            config_path: 配置文件路径（默认 presets_v2.yaml）
        """
        self.strategy_name = strategy_name

        if config_path is None:
            config_path = Path(__file__).parent.parent / 'presets_v2.yaml'

        # 加载策略配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        self.strategy_config = config_data['strategies'].get(strategy_name)
        if self.strategy_config is None:
            raise ValueError(f"策略 '{strategy_name}' 不存在")

        # 创建评分引擎
        self.scoring_engine = ScoringEngine(self.strategy_config)

        # 数据客户端
        self.sector_client = SectorClient()
        self.intraday_client = IntradayClient()
        self.capital_client = CapitalFlowClient()

    def run(self, stock_list: pd.DataFrame, client) -> List[Dict]:
        """
        运行策略

        Args:
            stock_list: 初步筛选后的股票列表（DataFrame）
            client: 数据提供者（用于获取K线数据）

        Returns:
            符合条件的股票列表（兼容旧格式）
        """
        logger.info(f'\n使用新架构策略: {self.strategy_config["name"]}')
        logger.info(f'说明: {self.strategy_config["description"]}')

        # 【性能优化】快速过滤：只处理符合基本条件的股票
        logger.info('\n[快速过滤] 预筛选股票...')
        filters = self.strategy_config.get('filters', {})
        liquidity = filters.get('liquidity', {})
        price_filter = filters.get('price', {})

        # 应用基础过滤条件
        filtered = stock_list.copy()

        if price_filter.get('change_min') is not None:
            filtered = filtered[filtered['change_pct'] >= price_filter['change_min']]

        if liquidity.get('turnover_min') is not None:
            filtered = filtered[filtered['turnover'] >= liquidity['turnover_min']]

        # 注意：腾讯数据源没有 amount 字段，跳过成交额过滤
        # 如果将来需要，可以从 volume * price 计算

        logger.info(f'  预筛选结果: {len(filtered)}/{len(stock_list)}只')

        if len(filtered) == 0:
            logger.warning('  没有股票通过预筛选')
            return []

        # 预加载板块数据（尝试一次，失败则跳过）
        logger.info('\n[数据准备] 加载板块数据...')
        try:
            sector_data = self.sector_client.get_all_sectors()
            if sector_data is not None:
                logger.info(f'  板块数据加载完成: {len(sector_data)}个板块')
            else:
                logger.warning('  板块数据加载失败，将使用默认值')
                self.sector_client = None  # 禁用后续板块数据获取
        except Exception as e:
            logger.warning(f'  板块数据加载失败: {e}，将使用默认值')
            self.sector_client = None

        # 增强股票数据
        logger.info('\n[数据增强] 计算高级指标...')
        enhanced_stocks = []

        from tqdm import tqdm
        for _, stock in tqdm(filtered.iterrows(), total=len(filtered), desc='  增强进度', unit='只'):
            try:
                enhanced = self._enhance_stock_data(stock, client)
                if enhanced:
                    enhanced_stocks.append(enhanced)
            except Exception as e:
                logger.debug(f"  增强数据失败({stock['code']}): {e}")
                continue

        logger.info(f'  数据增强完成: {len(enhanced_stocks)}/{len(filtered)}只')

        # 评分筛选
        logger.info('\n[策略评分] 多维度评分中...')
        results = self.scoring_engine.batch_evaluate(enhanced_stocks)

        logger.info(f'  评分完成: {len(results)}只通过筛选')

        # 转换为旧格式
        converted = self._convert_to_legacy_format(results)

        return converted

    def _enhance_stock_data(self, stock: pd.Series, client) -> Optional[Dict]:
        """
        增强股票数据：计算所有高级指标

        Args:
            stock: 股票基础数据
            client: 数据提供者

        Returns:
            增强后的股票数据字典
        """
        code = stock['code']

        # 转换为字典
        data = stock.to_dict()

        # 获取K线数据
        hist = client.get_stock_history(code, days=30)
        if hist is None or len(hist) < 10:
            return None

        data['hist_data'] = hist

        # 计算基础指标
        from stock_selector.indicators.kdj import kdj_k
        from stock_selector.indicators.rsi import rsi6

        try:
            data['kdj_k'] = float(kdj_k(hist['最高'], hist['最低'], hist['收盘']).iloc[-1])
        except:
            data['kdj_k'] = None

        try:
            data['rsi6'] = float(rsi6(hist['收盘']).iloc[-1])
        except:
            data['rsi6'] = None

        # 计算高级指标
        current_price = stock.get('price', hist['收盘'].iloc[-1])

        # 均线位置
        ma20 = calculate_ma(hist, period=20)
        if ma20:
            data['ma20'] = ma20
            data['ma_position'] = ma_position(current_price, ma20)
            data['ma20_support'] = check_ma_support(current_price, ma20)
        else:
            data['ma_position'] = None
            data['ma20_support'] = False

        # 相对强度（需要板块数据，失败则使用默认值）
        sector_name = stock.get('sector')
        if sector_name and self.sector_client:
            try:
                rel_strength = self.sector_client.calculate_relative_strength(
                    code,
                    stock.get('change_pct', 0),
                    sector_name
                )
                data['relative_strength'] = rel_strength
            except Exception as e:
                logger.debug(f"  获取相对强度失败({code}): {e}")
                data['relative_strength'] = 0  # 使用默认值
        else:
            data['relative_strength'] = 0  # 板块数据不可用，使用默认值

        # 近期涨跌幅
        data['recent_change_5d'] = recent_change(hist, days=5)
        data['recent_change_3d'] = recent_change(hist, days=3)

        # 连续涨跌天数
        data['consecutive_up_days'] = consecutive_days(hist['涨跌幅'], direction='up')
        data['consecutive_down_days'] = consecutive_days(hist['涨跌幅'], direction='down')

        # 突破检测
        is_breakout, breakout_pct = breakout_detection(hist, lookback_days=20)
        data['breakout'] = is_breakout
        data['breakout_pct'] = breakout_pct

        # 平台突破
        is_platform, platform_info = platform_detection(hist, lookback_days=20, tolerance=5.0)
        data['platform_breakout'] = is_platform
        data['platform_info'] = platform_info

        # 动能加速
        data['momentum_acceleration'] = momentum_acceleration(hist)

        # 成交量放大
        is_expanded, vol_ratio = volume_expansion(hist, days=5, threshold=1.5)
        data['volume_expansion'] = is_expanded
        data['volume_ratio'] = vol_ratio if vol_ratio else stock.get('volume_ratio', 0)

        # 资金流向数据（快速失败，避免超时）
        if self.capital_client:
            try:
                flow = self.capital_client.get_realtime_flow(code)
                if flow:
                    data['main_force_flow'] = flow['主力净流入']
                    data['main_force_ratio'] = flow['主力净占比']
                else:
                    # 第一次失败，禁用后续资金流向获取
                    self.capital_client = None
                    data['main_force_flow'] = 0
                    data['main_force_ratio'] = 0
            except Exception as e:
                logger.debug(f"  获取实时资金流向失败({code}): {e}")
                # 连接失败，禁用后续资金流向获取
                self.capital_client = None
                data['main_force_flow'] = 0
                data['main_force_ratio'] = 0
        else:
            data['main_force_flow'] = 0
            data['main_force_ratio'] = 0

        # 外盘占比
        outer_vol = stock.get('outer_vol', 0)
        inner_vol = stock.get('inner_vol', 0)
        total_vol = outer_vol + inner_vol
        data['outer_ratio'] = outer_vol / total_vol if total_vol > 0 else 0.5

        # 日内最高价距离（如果有分时数据）
        try:
            high_dist = self.intraday_client.get_today_high_distance(code, current_price)
            if high_dist:
                data['high_distance'] = high_dist['high_distance']
                data['is_near_high'] = high_dist['is_near_high']
        except:
            data['high_distance'] = None
            data['is_near_high'] = False

        return data

    def _convert_to_legacy_format(self, results: List[ScoringResult]) -> List[Dict]:
        """
        转换评分结果为旧格式（兼容现有报告系统）

        Args:
            results: 评分结果列表

        Returns:
            旧格式股票列表
        """
        converted = []

        for result in results:
            raw = result.raw_data

            # 提取评分明细
            breakdown_dict = {bd.category: bd.actual_score for bd in result.breakdown}

            converted.append({
                # 基础信息
                'code': result.code,
                'name': result.name,
                'price': raw.get('price', 0),
                'change_pct': raw.get('change_pct', 0),
                'turnover': raw.get('turnover', 0),
                'volume': raw.get('volume', 0),
                'amount': raw.get('amount', 0),
                'sector': raw.get('sector', ''),

                # 新增：评分信息
                'score': result.total_score,
                'score_breakdown': breakdown_dict,
                'signals': result.signals,
                'warnings': result.warnings,
                'reason': result.reason,

                # 技术指标
                'kdj_k': raw.get('kdj_k'),
                'rsi6': raw.get('rsi6'),
                'volume_ratio': raw.get('volume_ratio', 0),

                # 高级指标
                'relative_strength': raw.get('relative_strength'),
                'ma_position': raw.get('ma_position'),
                'recent_3day_change': raw.get('recent_change_3d', 0),
                'consecutive_up_days': raw.get('consecutive_up_days', 0),
                'breakout': raw.get('breakout', False),
                'platform_breakout': raw.get('platform_breakout', False),

                # 资金数据
                'main_force_flow': raw.get('main_force_flow', 0),
                'outer_ratio': raw.get('outer_ratio', 0.5) * 100,  # 转为百分比

                # K线数据（用于报告）
                'hist_data': raw.get('hist_data'),

                # 标记策略类型
                'strategy': self.strategy_name,
                'strategy_version': 'v2',
            })

        return converted


def load_v2_strategy(strategy_name: str) -> StrategyAdapter:
    """
    加载 v2 格式策略

    Args:
        strategy_name: 策略名称

    Returns:
        策略适配器

    Examples:
        >>> adapter = load_v2_strategy('ultra_short')
        >>> results = adapter.run(stock_list, client)
    """
    return StrategyAdapter(strategy_name)
