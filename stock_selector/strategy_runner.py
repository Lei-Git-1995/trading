#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技术形态选股交互入口，复用 stock_selector 现有数据源。"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from stock_selector.config import OUTPUT_DIR
from stock_selector.data.providers import list_providers
from stock_selector.data.smart_provider_manager import SmartProviderManager
from stock_selector.strategies.technical_selection import STRATEGIES, STRATEGY_MAP, TechnicalSelector


def show_strategies():
    print('\n可用技术选股策略：')
    print('-' * 90)
    for i, item in enumerate(STRATEGIES, 1):
        print('%2d. %-22s %-18s %s' % (i, item['id'], item['name'], item['description']))
    print(' A. all                   执行全部策略')
    print('-' * 90)


def choose_strategy(value):
    value = value.strip()
    if value.lower() in ('a', 'all', '全部'):
        return [item['id'] for item in STRATEGIES]
    result = []
    for raw in value.split(','):
        raw = raw.strip()
        if raw.isdigit() and 1 <= int(raw) <= len(STRATEGIES):
            result.append(STRATEGIES[int(raw) - 1]['id'])
        elif raw in STRATEGY_MAP:
            result.append(raw)
        else:
            raise ValueError('未知策略: %s' % raw)
    return result


def write_report(results, output):
    lines = ['# 技术形态选股结果', '', '**生成时间：** %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '']
    for strategy_id, rows in results.items():
        item = STRATEGY_MAP[strategy_id]
        lines.extend(['## %s（%s）' % (item['name'], strategy_id), '', item['description'], ''])
        if not rows:
            lines.extend(['未筛选出符合条件的股票。', ''])
            continue
        lines.extend(['| 代码 | 名称 | 最新价 | 当日涨幅 | 最新日期 | 条件说明 | 指标 |', '|---|---|---:|---:|---|---|---|'])
        for row in rows:
            metrics = json.dumps(row['metrics'], ensure_ascii=False, default=str).replace('|', '/')
            lines.append('| %s | %s | %s | %s | %s | %s | `%s` |' % (
                row['code'], row['name'], row.get('price', ''), row.get('change_pct', ''),
                row.get('latest_date', ''), row['reason'], metrics))
        lines.extend(['', '匹配数量：%d' % len(rows), ''])
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description='技术指标与周期形态选股')
    parser.add_argument('--strategy', help='策略编号、策略ID、all；多个策略用逗号分隔')
    parser.add_argument('--source', default='', help='数据源名称，留空由智能管理器选择')
    parser.add_argument('--days', type=int, default=150, help='历史 K 线天数')
    parser.add_argument('--limit', type=int, default=0, help='只处理行情列表前N只，0表示全部')
    parser.add_argument('--codes', help='只筛选指定代码，逗号分隔，便于测试')
    parser.add_argument('--output', help='Markdown 输出路径')
    parser.add_argument('--list-strategies', action='store_true')
    args = parser.parse_args(argv)

    show_strategies()
    if args.list_strategies:
        return 0
    try:
        strategy_ids = choose_strategy(args.strategy or input('请选择策略编号/ID（可多选，或 all）：'))
        manager = SmartProviderManager(args.source or None)
        provider = manager.get_provider()
        if provider is None:
            print('没有可用的数据源。')
            return 1
        stocks = provider.get_all_stocks()
        if stocks is None or stocks.empty:
            print('没有获取到股票行情列表。')
            return 1
        if args.codes:
            wanted = set(x.strip().zfill(6) for x in args.codes.split(',') if x.strip())
            stocks = stocks[stocks['code'].astype(str).isin(wanted)]
        print('数据源：%s，待处理股票：%d' % (manager.current_provider_name, len(stocks)))
        results = {}
        for strategy_id in strategy_ids:
            print('执行：%s' % STRATEGY_MAP[strategy_id]['name'])
            results[strategy_id] = TechnicalSelector.screen(provider=provider, stock_list=stocks,
                                                            strategy_id=strategy_id, days=args.days, limit=args.limit)
            print('  匹配：%d 只' % len(results[strategy_id]))
        output = args.output or str(OUTPUT_DIR / ('technical_%s.md' % datetime.now().strftime('%Y-%m-%d_%H%M%S')))
        write_report(results, output)
        print('报告：%s' % output)
        return 0
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。')
        return 1
    except Exception as exc:
        print('执行失败：%s' % exc)
        return 1


if __name__ == '__main__':
    sys.exit(main())
