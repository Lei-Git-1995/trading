"""
Markdown 选股报告：模板定义 + 渲染 + 输出

使用方式：
    generate(stocks, data_date, output_path, config) -> 写入文件并返回路径
    render_report(stocks, data_date, config)            -> 返回模板渲染后的字符串
"""

from datetime import datetime

# ---------------------------------------------------------------
# 报告模板（占位符由 render_report 填充）
# ---------------------------------------------------------------
REPORT_TEMPLATE = """# 每日短线选股报告

**行情数据日期：** {data_date}
**生成时间：** {generate_time}
**筛选数量：** {total_count} 只

---

## 📋 筛选条件

{conditions}

---

{result}

---

## ⚠️ 风险提示

1. **本报告仅供参考**，不构成任何投资建议
2. **短线操作风险较高**，请严格控制仓位
3. **建议止损位**：买入价下方 3-5%
4. **建议止盈位**：买入价上方 5-8%
5. **避免追高**，等待回调买入机会
6. **关注大盘走势**，系统性风险优先
7. **市场有风险，投资需谨慎**

---

## 💡 操作建议

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
- 持股期间密切关注盘面变化

---

*报告生成时间：{footer_time}*
*数据来源：{source}*
"""

NO_RESULT_BLOCK = """## ⚠️ 暂无符合条件的股票

所选交易日未发现符合所有筛选条件的股票。
建议放宽参数后重试，例如：

```bash
py -3.11 -m stock_selector.main --turnover 10 --change -1,4 --volume 1.2
```
"""


def _turnover_fmt(stock) -> str:
    t = stock.get('turnover')
    return f'{t:.2f}' if t is not None else '-'


def _outer_fmt(stock) -> str:
    """外盘占比格式化：缺失(如腾讯/新浪数据源)显示为 -"""
    v = stock.get('outer_ratio')
    if v is None or (isinstance(v, float) and v != v):  # NaN
        return '-'
    return f'{v:.1f}'


def _build_conditions(config) -> str:
    lines = [
        f'- ✅ 换手率 > {config.turnover_min}%',
        f'- ✅ 涨幅在 {config.change_min}% 到 {config.change_max}% 之间',
        f'- ✅ 量能比前两日平均放量 > {config.volume_ratio}倍',
    ]
    if config.check_outer_inner:
        lines.append('- ✅ 外盘 > 内盘（资金净流入，主动买入 > 主动卖出）')
    if config.check_kdj:
        lines.append('- ✅ KDJ指标 < 80（未超买）')
    if config.check_rsi:
        lines.append('- ✅ RSI指标 < 70（未超买）')
    if config.top_per_sector > 0:
        lines.append(f'- ✅ 每个板块最多选取 {config.top_per_sector} 只')
    off = []
    if not config.check_outer_inner:
        off.append('外盘>内盘')
    if not config.check_kdj:
        off.append('KDJ未超买')
    if not config.check_rsi:
        off.append('RSI未超买')
    if off:
        lines.append('- ⏸️ 本次未启用：' + '、'.join(off))
    return '\n'.join(lines)


def _render_pick_table(stocks) -> str:
    """Top 20 表格"""
    lines = ['### Top 20 精选\n', '| 排名 | 代码 | 名称 | 板块 | 最新价 | 涨幅% | 换手% | 量比 | 外盘% | 评分 |',
             '|------|------|------|------|--------|-------|-------|------|-------|------|']
    for i, s in enumerate(stocks[:20], 1):
        # 炸板标记
        name_with_tag = s['name'] + ('(炸板)' if s.get('is_failed_limit', False) else '')
        lines.append(
            f"| {i} | {s['code']} | {name_with_tag} | {s['sector'][:6]} | "
            f"{s['price']:.2f} | {s['change_pct']:.2f} | {_turnover_fmt(s)} | "
            f"{s['volume_ratio']:.2f} | {_outer_fmt(s)} | {s['score']} |"
        )
    return '\n'.join(lines)


def _fmt_metric(v) -> str:
    """指标值格式化：None 显示为 -"""
    return '-' if v is None else f'{v:.1f}'


def _render_detail_blocks(stocks) -> str:
    """Top 5 详细分析"""
    parts = ['---', '', '## 📊 Top 5 详细分析', '']
    for i, s in enumerate(stocks[:5], 1):
        flow = '净流入' if s.get('outer_ratio') is not None and s['outer_ratio'] == s['outer_ratio'] and s['outer_ratio'] > 50 else (
            '净流出' if s.get('outer_ratio') is not None and s['outer_ratio'] == s['outer_ratio'] else '数据源未提供')
        # 炸板标记
        name_with_tag = f"{s['name']}（{s['code']}）"
        if s.get('is_failed_limit', False):
            name_with_tag += ' ⚠️炸板'

        orr = s.get('outer_ratio')
        inner = s.get('inner_ratio')
        _has_outer = orr is not None and not (isinstance(orr, float) and orr != orr)

        L = [
            f'### {i}. {name_with_tag}',
            '',
            f'**综合评分：** {s["score"]} 分',
            f'**所属板块：** {s["sector"]}',
            '',
            '**基本信息：**',
            f'- 最新价：{s["price"]:.2f} 元',
            f'- 涨跌幅：{s["change_pct"]:.2f}%',
            f'- 换手率：{_turnover_fmt(s)}%',
            f'- 量比：{s["volume_ratio"]:.2f} 倍',
            (f'- 外盘占比：{orr:.1f}%（内盘：{inner:.1f}%）'
             if _has_outer
             else '- 外盘占比：数据源未提供（腾讯/新浪不含外盘/内盘）'),
            f'- 资金流向：{flow}',
            '',
            '**技术指标：**',
            f'- KDJ_K：{_fmt_metric(s["kdj_k"])}',
            f'- RSI(6)：{_fmt_metric(s["rsi6"])}',
            f'- 近3日累计涨幅：{s["recent_3day_change"]:.2f}%',
            '',
            '**近5日走势：**',
            '',
            '| 日期 | 收盘价 | 涨跌幅% | 换手率% | 成交量(手) |',
            '|------|--------|---------|---------|------------|',
        ]
        hist = s.get('hist_data')
        if hist is not None and not hist.empty:
            for _, r in hist.iterrows():
                t = '-' if str(r['换手率']) == 'nan' else f'{r["换手率"]:.2f}'
                L.append(
                    f"| {r['日期']} | {r['收盘']:.2f} | {r['涨跌幅']:.2f} | {t} | {int(r['成交量'])} |"
                )

        reasons = _build_reasons(s)
        if reasons:
            L.append('')
            L.append('**选股理由：**')
            L.extend(reasons)

        # 如果是炸板,添加警告
        if s.get('is_failed_limit', False):
            L.append('')
            L.append('**⚠️ 风险提示：该股今日出现炸板(涨停后打开),存在较大抛压,短线风险较高,建议谨慎**')

        parts.append('\n'.join(L))
        parts.append('')

    return '\n'.join(parts).rstrip('\n')


def _build_reasons(s) -> list:
    reasons = []
    if 1.5 <= s['change_pct'] <= 2.5:
        reasons.append('- 涨幅适中，处于最佳区间')
    if s.get('turnover') is not None and 15 <= s['turnover'] <= 25:
        reasons.append('- 换手率理想，市场活跃')
    if 1.5 <= s['volume_ratio'] <= 3:
        reasons.append('- 明显放量，资金关注度高')
    if s.get('kdj_k') is not None and 30 <= s['kdj_k'] <= 60:
        reasons.append('- KDJ处于健康区间')
    if s.get('rsi6') is not None and 40 <= s['rsi6'] <= 60:
        reasons.append('- RSI强弱适中')
    if 5 <= s['recent_3day_change'] <= 15:
        reasons.append('- 近期走势稳健')
    return reasons


def _render_full_list(stocks) -> str:
    """Top20 之外的完整候选列表"""
    if len(stocks) <= 20:
        return ''
    parts = [f'\n---\n', f'## 📑 完整候选列表（21-{len(stocks)}）\n',
             '\n| 代码 | 名称 | 板块 | 最新价 | 涨幅% | 换手% | 量比 | 评分 |',
             '|------|------|------|--------|-------|-------|------|------|']
    for s in stocks[20:]:
        # 炸板标记
        name_with_tag = s['name'] + ('(炸板)' if s.get('is_failed_limit', False) else '')
        parts.append(
            f"| {s['code']} | {name_with_tag} | {s['sector'][:6]} | "
            f"{s['price']:.2f} | {s['change_pct']:.2f} | {_turnover_fmt(s)} | "
            f"{s['volume_ratio']:.2f} | {s['score']} |"
        )
    return '\n'.join(parts)


def _render_result(stocks) -> str:
    """推荐结果区（模板中的 {result} 占位）"""
    if not stocks:
        return NO_RESULT_BLOCK
    blocks = [
        f'## 🎯 推荐股票列表（共 {len(stocks)} 只）\n',
        _render_pick_table(stocks),
        '\n' + _render_detail_blocks(stocks),
        _render_full_list(stocks),
    ]
    return '\n'.join(b for b in blocks if b)


def render_report(stocks, data_date: str, config) -> str:
    """按模板渲染完整 Markdown 报告"""
    now = datetime.now()
    ctx = {
        'data_date': data_date,
        'generate_time': now.strftime('%Y年%m月%d日 %H:%M'),
        'total_count': len(stocks),
        'conditions': _build_conditions(config),
        'result': _render_result(stocks),
        'footer_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'source': '东方财富 / 腾讯行情',
    }
    return REPORT_TEMPLATE.format(**ctx)


def generate(stocks, data_date: str, output_path: str, config) -> str:
    """渲染并写入文件，返回文件路径"""
    content = render_report(stocks, data_date, config)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return output_path