"""
v2 架构专用 Markdown 报告生成器

增强功能:
1. 展示多维度评分明细
2. 显示触发的信号
3. 风险提示
4. 评分雷达图（ASCII）
"""

from datetime import datetime
from typing import List, Dict


REPORT_V2_TEMPLATE = """# 每日短线选股报告 v2.0

**策略名称：** {strategy_name}
**策略描述：** {strategy_description}
**行情数据日期：** {data_date}
**生成时间：** {generate_time}
**筛选数量：** {total_count} 只

---

## 📊 评分概览

{score_summary}

---

## 📋 筛选结果

{result_table}

---

{detailed_results}

---

## 📈 策略配置

### 基础过滤条件（硬条件）
{filter_conditions}

### 评分维度（满分100分）
{scoring_dimensions}

### 风险控制
{risk_control}

---

## ⚠️ 风险提示

1. **本报告仅供参考**，不构成任何投资建议
2. **v2 评分系统为辅助工具**，最终决策需结合盘面和基本面
3. **高分不等于必涨**，市场环境和系统性风险优先
4. **短线操作风险较高**，请严格控制仓位
5. **建议止损位**：买入价下方 3-5%
6. **建议止盈位**：买入价上方 5-8%
7. **市场有风险，投资需谨慎**

---

## 💡 操作建议

### 评分解读
- **85分以上**：综合条件极佳，重点关注
- **75-85分**：条件良好，可考虑配置
- **60-75分**：基本符合，需结合盘面
- **60分以下**：未通过筛选

### 买入时机
- 尾盘14:50后观察，次日开盘或回调时买入
- 如遇高开，等待回调至分时均线附近
- 如遇低开，观察是否快速拉起

### 仓位管理
- 单只股票仓位不超过总资金的 10-15%
- 同时持有不超过 3-5 只股票
- 保留 30% 以上现金应对风险

### 持仓周期
- 短线持股周期：1-3 个交易日
- 达到止盈目标果断离场
- 触及止损位立即止损

---

*报告生成时间：{footer_time}*
*选股系统：stock_selector v2.0 多维度评分架构*
"""


def generate_v2_report(results: List[Dict], data_date: str, output_path: str, strategy_config: Dict) -> str:
    """
    生成 v2 架构的 Markdown 报告

    Args:
        results: 选股结果列表（已包含评分信息）
        data_date: 数据日期
        output_path: 输出文件路径
        strategy_config: 策略配置

    Returns:
        输出文件路径
    """
    now = datetime.now()
    generate_time = now.strftime('%Y-%m-%d %H:%M:%S')
    footer_time = now.strftime('%Y-%m-%d %H:%M')

    # 提取策略信息
    strategy_name = strategy_config.get('name', '未命名策略')
    strategy_description = strategy_config.get('description', '')

    # 评分概览
    if results:
        scores = [r['score'] for r in results]
        avg_score = sum(scores) / len(scores)
        max_score = max(scores)
        min_score = min(scores)

        score_summary = f"""
- **平均得分**: {avg_score:.1f} 分
- **最高得分**: {max_score:.1f} 分
- **最低得分**: {min_score:.1f} 分
- **得分分布**:
  - 85分以上: {len([s for s in scores if s >= 85])} 只
  - 75-85分: {len([s for s in scores if 75 <= s < 85])} 只
  - 60-75分: {len([s for s in scores if 60 <= s < 75])} 只
"""
    else:
        score_summary = "暂无符合条件的股票"

    # 结果表格
    result_table = _generate_result_table(results)

    # 详细结果
    detailed_results = _generate_detailed_results(results)

    # 策略配置展示
    filter_conditions = _format_filters(strategy_config.get('filters', {}))
    scoring_dimensions = _format_signals(strategy_config.get('signals', {}))
    risk_control = _format_risk(strategy_config.get('risk', {}))

    # 填充模板
    content = REPORT_V2_TEMPLATE.format(
        strategy_name=strategy_name,
        strategy_description=strategy_description,
        data_date=data_date,
        generate_time=generate_time,
        total_count=len(results),
        score_summary=score_summary,
        result_table=result_table,
        detailed_results=detailed_results,
        filter_conditions=filter_conditions,
        scoring_dimensions=scoring_dimensions,
        risk_control=risk_control,
        footer_time=footer_time
    )

    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return output_path


def _generate_result_table(results: List[Dict]) -> str:
    """生成结果表格"""
    if not results:
        return "暂无符合条件的股票"

    lines = [
        "| 排名 | 代码 | 名称 | 得分 | 涨幅 | 换手率 | 相对强度 | 主力流入 | 信号数 |",
        "|------|------|------|------|------|--------|----------|----------|--------|"
    ]

    for i, stock in enumerate(results[:30], 1):  # 最多显示30只
        code = stock.get('code', '')
        name = stock.get('name', '')
        score = stock.get('score', 0)
        change = stock.get('change_pct', 0)
        turnover = stock.get('turnover', 0)
        rel_strength = stock.get('relative_strength')
        main_flow = stock.get('main_force_flow', 0)
        signal_count = len(stock.get('signals', []))

        rel_str = f"{rel_strength:+.1f}%" if rel_strength is not None else "N/A"
        flow_str = f"{main_flow:.0f}万" if main_flow != 0 else "N/A"

        lines.append(
            f"| {i} | {code} | {name} | **{score:.1f}** | {change:+.2f}% | {turnover:.1f}% | {rel_str} | {flow_str} | {signal_count} |"
        )

    return "\n".join(lines)


def _generate_detailed_results(results: List[Dict]) -> str:
    """生成详细结果"""
    if not results:
        return ""

    sections = []

    for i, stock in enumerate(results[:10], 1):  # 详细展示前10只
        code = stock.get('code', '')
        name = stock.get('name', '')
        score = stock.get('score', 0)
        change = stock.get('change_pct', 0)
        price = stock.get('price', 0)
        turnover = stock.get('turnover', 0)

        # 评分明细
        breakdown = stock.get('score_breakdown', {})
        breakdown_lines = []
        for category, cat_score in breakdown.items():
            breakdown_lines.append(f"  - {category}: {cat_score:.1f}分")

        # 触发信号
        signals = stock.get('signals', [])
        signal_lines = []
        for signal in signals[:5]:  # 最多显示5个信号
            signal_lines.append(f"  - ✓ {signal}")

        # 风险警告
        warnings = stock.get('warnings', [])
        warning_lines = []
        for warning in warnings[:3]:  # 最多显示3个警告
            warning_lines.append(f"  - ⚠ {warning}")

        # 技术指标
        tech_info = []
        if stock.get('relative_strength') is not None:
            tech_info.append(f"相对强度: {stock['relative_strength']:+.1f}%")
        if stock.get('ma_position') is not None:
            tech_info.append(f"MA20距离: {stock['ma_position']:+.1f}%")
        if stock.get('consecutive_up_days'):
            tech_info.append(f"连续上涨: {stock['consecutive_up_days']}天")

        # 评价理由
        reason = stock.get('reason', '')

        section = f"""
### {i}. {code} {name}

**综合得分**: {score:.1f}/100 {'🔥' if score >= 85 else '✓' if score >= 75 else ''}

**基本信息**:
- 价格: {price:.2f} 元
- 涨幅: {change:+.2f}%
- 换手率: {turnover:.1f}%

**评分明细**:
{chr(10).join(breakdown_lines) if breakdown_lines else '  无明细'}

**触发信号**:
{chr(10).join(signal_lines) if signal_lines else '  无特殊信号'}

{('**风险提示**:' + chr(10) + chr(10).join(warning_lines)) if warning_lines else ''}

**技术指标**: {' | '.join(tech_info) if tech_info else '无'}

**评价**: {reason}

---
"""
        sections.append(section)

    return "\n".join(sections)


def _format_filters(filters: Dict) -> str:
    """格式化过滤条件"""
    lines = []

    liquidity = filters.get('liquidity', {})
    if liquidity:
        lines.append("**流动性要求**:")
        if 'turnover_min' in liquidity:
            lines.append(f"- 换手率: ≥{liquidity['turnover_min']}%")
        if 'amount_min' in liquidity:
            lines.append(f"- 成交额: ≥{liquidity['amount_min']}亿")
        if 'volume_ratio_min' in liquidity:
            lines.append(f"- 量比: ≥{liquidity['volume_ratio_min']}")

    price_filter = filters.get('price', {})
    if price_filter:
        lines.append("\n**价格要求**:")
        if 'change_min' in price_filter and 'change_max' in price_filter:
            lines.append(f"- 涨跌幅: {price_filter['change_min']}% ~ {price_filter['change_max']}%")
        if 'price_min' in price_filter:
            lines.append(f"- 价格: ≥{price_filter['price_min']}元")

    board = filters.get('board', {})
    if board:
        lines.append("\n**板块要求**:")
        if not board.get('allow_st', True):
            lines.append("- 不选ST股票")
        if not board.get('allow_cyb', True):
            lines.append("- 过滤创业板")
        if not board.get('allow_kcb', True):
            lines.append("- 过滤科创板")

    return "\n".join(lines) if lines else "无特殊要求"


def _format_signals(signals: Dict) -> str:
    """格式化评分维度"""
    lines = []

    for category, config in signals.items():
        weight = config.get('weight', 0)
        lines.append(f"\n**{category}** ({weight}分):")

        metrics = config.get('metrics', [])
        for metric in metrics:
            name = metric.get('name', '')
            score = metric.get('score', 0)
            lines.append(f"- {name}: {score}分")

    return "\n".join(lines) if lines else "无评分维度"


def _format_risk(risk: Dict) -> str:
    """格式化风险控制"""
    deduct = risk.get('deduct', [])

    if not deduct:
        return "无特殊风险控制"

    lines = []
    for rule in deduct:
        name = rule.get('name', '')
        threshold = rule.get('threshold', '')
        penalty = rule.get('penalty', 0)
        lines.append(f"- {name} > {threshold} → 扣{abs(penalty)}分")

    return "\n".join(lines)
