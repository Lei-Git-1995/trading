#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交互式选股入口，支持 CSV 股票池和在线股票代码列表。"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from stock_analysis.analyzer import StockAnalyzer
    from stock_analysis.config import get_report_dir
    from stock_analysis.core.selection import STRATEGIES, STRATEGY_MAP, StockSelector
    from stock_analysis.core.validator import DataValidator
    from stock_analysis.datasources.csv_source import CSVDataSource
else:
    from .analyzer import StockAnalyzer
    from .config import get_report_dir
    from .core.selection import STRATEGIES, STRATEGY_MAP, StockSelector
    from .core.validator import DataValidator
    from .datasources.csv_source import CSVDataSource


def show_strategies():
    print('\n可用选股策略：')
    print('-' * 78)
    for index, item in enumerate(STRATEGIES, 1):
        print('%2d. %-20s %-18s %s' % (index, item['id'], item['name'], item['description']))
    print(' A. all                 执行全部策略')
    print('-' * 78)


def _read_csv(path, code=None, name=None):
    source = CSVDataSource(str(path), stock_code=code, stock_name=name)
    return source.stock_code, source.stock_name, source.df


def load_csv_universe(path):
    """加载单个 CSV、含代码列的合并 CSV 或 CSV 目录。"""
    path = Path(path)
    if path.is_dir():
        universe = []
        for csv_path in sorted(path.glob('*.csv')):
            try:
                universe.append(_read_csv(csv_path, csv_path.stem, csv_path.stem))
            except Exception as exc:
                print('[跳过] %s: %s' % (csv_path.name, exc))
        return universe
    if not path.exists():
        raise FileNotFoundError('输入路径不存在: %s' % path)

    raw = pd.read_csv(str(path), encoding='utf-8-sig')
    code_col = next((c for c in ['股票代码', '代码', 'code', 'Code'] if c in raw.columns), None)
    if code_col:
        name_col = next((c for c in ['股票名称', '名称', 'name', 'Name'] if c in raw.columns), None)
        universe = []
        for code, group in raw.groupby(code_col, sort=False):
            code = str(code).split('.')[0].zfill(6)
            name = str(group[name_col].iloc[0]) if name_col else code
            data = group.drop(columns=[c for c in [code_col, name_col] if c]).copy()
            valid, missing = DataValidator.validate_required_columns(
                data, ['日期', '开盘', '收盘', '最高', '最低', '成交量'])
            if not valid:
                print('[跳过] %s 缺少列: %s' % (code, missing))
                continue
            universe.append((code, name, DataValidator.clean_data(data)))
        return universe
    return [_read_csv(path, path.stem, path.stem)]


def load_online_universe(codes, days, source):
    universe = []
    for code in codes:
        code = code.strip().zfill(6)
        if not code:
            continue
        try:
            analyzer = StockAnalyzer(code) if source == 'auto' else StockAnalyzer.from_datasource(code, source)
            data = analyzer.load_data(days=days)
            name = (analyzer.stock_info or {}).get('股票名称', code)
            universe.append((code, name, data))
        except Exception as exc:
            print('[跳过] %s: %s' % (code, exc))
    return universe


def _strategy_ids(value):
    if value.lower() in ('all', 'a', '全部'):
        return [item['id'] for item in STRATEGIES]
    ids = []
    for item in [v.strip() for v in value.split(',') if v.strip()]:
        if item.isdigit() and 1 <= int(item) <= len(STRATEGIES):
            ids.append(STRATEGIES[int(item) - 1]['id'])
        elif item in STRATEGY_MAP:
            ids.append(item)
        else:
            raise ValueError('未知策略: %s' % item)
    return ids


def render_markdown(results, source_desc, output_path):
    lines = ['# 选股结果', '', '**生成时间：** %s  ' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             '**数据来源：** %s  ' % source_desc, '**策略数量：** %d' % len(results), '']
    for strategy_id, result in results.items():
        item = STRATEGY_MAP[strategy_id]
        lines.extend(['## %s（%s）' % (item['name'], strategy_id), '', item['description'], ''])
        if result.empty:
            lines.extend(['未筛选出符合条件的股票。', ''])
            continue
        lines.extend(['| 股票代码 | 股票名称 | 最新日期 | 条件说明 | 指标详情 |', '|---|---|---|---|---|'])
        for _, row in result.iterrows():
            metrics = json.dumps(row.get('指标', {}), ensure_ascii=False, default=str).replace('|', '/')
            lines.append('| %s | %s | %s | %s | `%s` |' % (
                row.get('股票代码', ''), row.get('股票名称', ''), row.get('最新日期', ''),
                row.get('说明', ''), metrics))
        lines.extend(['', '匹配数量：%d' % len(result), ''])
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description='股票固定指标与周期形态选股工具')
    parser.add_argument('--strategy', help='策略编号、策略ID、all，多个策略用逗号分隔')
    parser.add_argument('--input', help='CSV文件或CSV目录；含股票代码列时可一次筛选多个股票')
    parser.add_argument('--codes', help='在线模式股票代码，逗号分隔')
    parser.add_argument('--codes-file', help='在线模式股票代码文件，每行一个代码')
    parser.add_argument('--source', choices=['auto', 'eastmoney', 'tencent'], default='auto')
    parser.add_argument('--days', type=int, default=150, help='在线模式获取历史天数')
    parser.add_argument('--output', help='结果 Markdown 输出路径')
    parser.add_argument('--list-strategies', action='store_true', help='只显示策略列表')
    args = parser.parse_args(argv)

    show_strategies()
    if args.list_strategies:
        return 0
    try:
        strategy_ids = _strategy_ids(args.strategy or input('请选择策略编号/ID（可多选，或 all）：').strip())
        if args.input:
            universe, source_desc = load_csv_universe(args.input), args.input
        else:
            codes = args.codes
            if args.codes_file:
                codes = ','.join(line.strip() for line in Path(args.codes_file).read_text(encoding='utf-8').splitlines() if line.strip())
            codes = codes or input('请输入股票代码（逗号分隔）：').strip()
            universe, source_desc = load_online_universe(codes.split(','), args.days, args.source), '%s在线数据' % args.source
        if not universe:
            print('没有可用于筛选的数据。')
            return 1
        results = {}
        for strategy_id in strategy_ids:
            result = StockSelector.select(universe, strategy_id)
            results[strategy_id] = result
            print('[%s] %s：匹配 %d 只' % (strategy_id, STRATEGY_MAP[strategy_id]['name'], len(result)))
        output_path = args.output or str(get_report_dir() / ('selection_%s.md' % datetime.now().strftime('%Y%m%d_%H%M%S')))
        render_markdown(results, source_desc, output_path)
        print('结果已保存：%s' % output_path)
        return 0
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。')
        return 1
    except Exception as exc:
        print('执行失败：%s' % exc)
        return 1


if __name__ == '__main__':
    sys.exit(main())
