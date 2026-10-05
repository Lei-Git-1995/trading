"""评分引擎：多维度股票评分系统

从"硬过滤"升级到"多维度评分+风险控制"
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np


@dataclass
class ScoreBreakdown:
    """评分明细"""
    category: str           # 类别（如momentum/technical/capital_flow）
    max_score: int          # 满分
    actual_score: float     # 实际得分
    metrics: Dict[str, float]  # 各指标得分明细
    signals: List[str] = field(default_factory=list)  # 触发的信号


@dataclass
class ScoringResult:
    """评分结果"""
    code: str
    name: str
    total_score: float
    passed: bool
    breakdown: List[ScoreBreakdown]
    risk_penalty: float
    signals: List[str]
    warnings: List[str]
    reason: str
    raw_data: Dict = field(default_factory=dict)


class ScoringEngine:
    """
    多维度评分引擎

    架构:
    1. 基础过滤 (filters) - 硬条件，不通过直接淘汰
    2. 信号评分 (signals) - 多维度打分，每个维度有权重
    3. 风险控制 (risk) - 识别风险因素，扣分或警告
    4. 综合排序 - 按总分排序，取Top N
    """

    def __init__(self, strategy_config: Dict):
        """
        Args:
            strategy_config: 策略配置（YAML加载后的字典）
        """
        self.config = strategy_config
        self.filters = strategy_config.get('filters', {})
        self.signals = strategy_config.get('signals', {})
        self.risk = strategy_config.get('risk', {})
        self.output = strategy_config.get('output', {})

    def evaluate(self, stock_data: Dict) -> Optional[ScoringResult]:
        """
        评估单只股票

        Args:
            stock_data: 股票数据，包含:
                - 基础数据: code, name, price, change_pct, turnover, volume等
                - K线数据: hist_data (DataFrame)
                - 资金数据: main_force_flow, outer_ratio等
                - 技术指标: kdj_k, rsi6, ma20等
                - 高级指标: relative_strength, ma_position等

        Returns:
            ScoringResult 或 None（未通过基础过滤）
        """
        code = stock_data.get('code')
        name = stock_data.get('name', '')

        # 第一步：基础过滤
        filter_passed, filter_reason = self._apply_filters(stock_data)
        if not filter_passed:
            return None

        # 第二步：信号评分
        breakdown, total_score, signals = self._apply_signals(stock_data)

        # 第三步：风险控制
        risk_penalty, warnings = self._apply_risk_control(stock_data)
        total_score += risk_penalty

        # 第四步：判断是否通过
        min_score = self.output.get('min_score', 60)
        passed = total_score >= min_score

        # 生成评价理由
        reason = self._generate_reason(stock_data, breakdown, signals, warnings)

        return ScoringResult(
            code=code,
            name=name,
            total_score=round(total_score, 1),
            passed=passed,
            breakdown=breakdown,
            risk_penalty=risk_penalty,
            signals=signals,
            warnings=warnings,
            reason=reason,
            raw_data=stock_data
        )

    def _apply_filters(self, stock_data: Dict) -> tuple[bool, str]:
        """
        应用基础过滤器（硬条件）

        Returns:
            (是否通过, 未通过原因)
        """
        filters = self.filters

        # 流动性过滤
        liquidity = filters.get('liquidity', {})
        turnover = stock_data.get('turnover', 0)
        amount = stock_data.get('amount', 0)  # 亿
        volume_ratio = stock_data.get('volume_ratio', 0)

        if 'turnover_min' in liquidity and turnover < liquidity['turnover_min']:
            return False, f"换手率{turnover:.1f}%低于{liquidity['turnover_min']}%"

        if 'turnover_max' in liquidity and turnover > liquidity['turnover_max']:
            return False, f"换手率{turnover:.1f}%高于{liquidity['turnover_max']}%"

        if 'amount_min' in liquidity and amount < liquidity['amount_min']:
            return False, f"成交额{amount:.1f}亿低于{liquidity['amount_min']}亿"

        if 'volume_ratio_min' in liquidity and volume_ratio < liquidity['volume_ratio_min']:
            return False, f"量比{volume_ratio:.1f}低于{liquidity['volume_ratio_min']}"

        # 价格过滤
        price_filter = filters.get('price', {})
        change_pct = stock_data.get('change_pct', 0)
        price = stock_data.get('price', 0)

        if 'change_min' in price_filter and change_pct < price_filter['change_min']:
            return False, f"涨幅{change_pct:.2f}%低于{price_filter['change_min']}%"

        if 'change_max' in price_filter and change_pct > price_filter['change_max']:
            return False, f"涨幅{change_pct:.2f}%高于{price_filter['change_max']}%"

        if 'price_min' in price_filter and price < price_filter['price_min']:
            return False, f"价格{price:.2f}低于{price_filter['price_min']}"

        if 'price_max' in price_filter and price > price_filter['price_max']:
            return False, f"价格{price:.2f}高于{price_filter['price_max']}"

        # 板块过滤
        board = filters.get('board', {})
        code = stock_data.get('code', '')

        if not board.get('allow_st', False):
            name = stock_data.get('name', '')
            if 'ST' in name or 'st' in name:
                return False, "ST股票"

        if not board.get('allow_cyb', True):
            if code.startswith('3'):
                return False, "创业板"

        if not board.get('allow_kcb', True):
            if code.startswith('688') or code.startswith('689'):
                return False, "科创板"

        return True, ""

    def _apply_signals(self, stock_data: Dict) -> tuple[List[ScoreBreakdown], float, List[str]]:
        """
        应用信号评分

        Returns:
            (评分明细列表, 总分, 触发信号列表)
        """
        breakdown = []
        total_score = 0.0
        all_signals = []

        signals_config = self.signals

        # 遍历各评分维度
        for category, config in signals_config.items():
            weight = config.get('weight', 0)
            metrics_config = config.get('metrics', [])

            category_score = 0.0
            category_max = sum(m.get('score', 0) for m in metrics_config)
            category_metrics = {}
            category_signals = []

            # 计算该维度下各指标得分
            for metric_config in metrics_config:
                metric_name = metric_config.get('name')
                max_score = metric_config.get('score', 0)

                score, signal = self._evaluate_metric(stock_data, metric_config)
                category_score += score
                category_metrics[metric_name] = score

                if signal:
                    category_signals.append(signal)
                    all_signals.append(signal)

            breakdown.append(ScoreBreakdown(
                category=category,
                max_score=category_max,
                actual_score=round(category_score, 1),
                metrics=category_metrics,
                signals=category_signals
            ))

            total_score += category_score

        return breakdown, total_score, all_signals

    def _evaluate_metric(self, stock_data: Dict, metric_config: Dict) -> tuple[float, Optional[str]]:
        """
        评估单个指标

        Returns:
            (得分, 触发信号描述)
        """
        metric_name = metric_config.get('name')
        max_score = metric_config.get('score', 0)
        value = stock_data.get(metric_name)

        if value is None:
            return 0.0, None

        # 检查最小值
        if 'min' in metric_config and value < metric_config['min']:
            return 0.0, None

        # 检查最大值
        if 'max' in metric_config and value > metric_config['max']:
            return 0.0, None

        # 检查最佳区间
        optimal = metric_config.get('optimal')
        if optimal and len(optimal) == 2:
            opt_min, opt_max = optimal
            if opt_min <= value <= opt_max:
                # 最佳区间：满分
                signal = f"{metric_name}={value:.2f} (最佳)"
                return max_score, signal
            else:
                # 非最佳区间：部分分数
                # 计算距离最佳区间的远近
                if value < opt_min:
                    ratio = value / opt_min
                elif value > opt_max:
                    ratio = opt_max / value
                else:
                    ratio = 1.0
                score = max_score * max(0.5, ratio)
                return score, None
        else:
            # 没有最佳区间：通过即给满分
            signal = f"{metric_name}={value:.2f}"
            return max_score, signal

    def _apply_risk_control(self, stock_data: Dict) -> tuple[float, List[str]]:
        """
        应用风险控制

        Returns:
            (扣分, 警告列表)
        """
        risk_config = self.risk.get('deduct', [])
        total_penalty = 0.0
        warnings = []

        for rule in risk_config:
            risk_name = rule.get('name')
            threshold = rule.get('threshold')
            penalty = rule.get('penalty', 0)

            value = stock_data.get(risk_name)
            if value is None:
                continue

            # 判断是否触发风险
            triggered = False
            if isinstance(threshold, (int, float)):
                triggered = value > threshold
            elif isinstance(threshold, dict):
                # 复杂条件
                pass

            if triggered:
                total_penalty += penalty
                warnings.append(f"{risk_name}={value:.1f}超过{threshold}，扣{-penalty}分")

        return total_penalty, warnings

    def _generate_reason(
        self,
        stock_data: Dict,
        breakdown: List[ScoreBreakdown],
        signals: List[str],
        warnings: List[str]
    ) -> str:
        """生成评价理由"""
        parts = []

        # 主要信号
        if signals:
            parts.append(f"信号: {', '.join(signals[:3])}")

        # 警告
        if warnings:
            parts.append(f"风险: {warnings[0]}")

        # 评分亮点
        top_category = max(breakdown, key=lambda x: x.actual_score / x.max_score if x.max_score > 0 else 0)
        parts.append(f"{top_category.category}得分{top_category.actual_score}/{top_category.max_score}")

        return " | ".join(parts)

    def batch_evaluate(self, stock_list: List[Dict]) -> List[ScoringResult]:
        """
        批量评估

        Args:
            stock_list: 股票数据列表

        Returns:
            通过筛选的股票评分结果列表（按得分排序）
        """
        results = []

        for stock_data in stock_list:
            result = self.evaluate(stock_data)
            if result and result.passed:
                results.append(result)

        # 按得分排序
        results.sort(key=lambda x: x.total_score, reverse=True)

        # 取Top N
        top_n = self.output.get('top_n', 0)
        if top_n > 0:
            results = results[:top_n]

        # 板块分组限制
        if self.output.get('group_by_sector', False):
            results = self._apply_sector_limit(results)

        return results

    def _apply_sector_limit(self, results: List[ScoringResult]) -> List[ScoringResult]:
        """应用板块数量限制"""
        max_per_sector = self.output.get('max_per_sector', 0)
        if max_per_sector <= 0:
            return results

        sector_count = {}
        filtered = []

        for result in results:
            sector = result.raw_data.get('sector', '未知')
            count = sector_count.get(sector, 0)

            if count < max_per_sector:
                filtered.append(result)
                sector_count[sector] = count + 1

        return filtered
