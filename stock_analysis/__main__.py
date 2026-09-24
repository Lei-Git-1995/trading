#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行工具
提供统一的命令行接口
"""

import sys
import argparse
from pathlib import Path
from .analyzer import StockAnalyzer
from .datasources import DataSourceFactory
from . import __version__


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description=f'股票技术分析工具 v{__version__}',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 分析股票（自动选择最优数据源）
  python -m stock_analysis 600519

  # 指定数据源
  python -m stock_analysis 600519 --source eastmoney

  # 从CSV分析
  python -m stock_analysis --csv data.csv --code 600519 --name 贵州茅台

  # 指定输出路径
  python -m stock_analysis 600519 -o reports/600519.md

  # 查看数据源状态
  python -m stock_analysis --list-sources
        """
    )

    parser.add_argument('stock_code', nargs='?', help='股票代码（6位数字）')
    parser.add_argument('-s', '--source', choices=['eastmoney', 'tencent', 'auto'],
                        default='auto', help='数据源（默认: auto自动选择）')
    parser.add_argument('-o', '--output', help='输出报告路径')
    parser.add_argument('-t', '--template', help='自定义模板路径')
    parser.add_argument('-d', '--days', type=int, default=60,
                        help='获取K线天数（默认: 60）')

    # CSV模式
    csv_group = parser.add_argument_group('CSV模式')
    csv_group.add_argument('--csv', help='CSV文件路径')
    csv_group.add_argument('--code', help='股票代码（CSV模式）')
    csv_group.add_argument('--name', help='股票名称（CSV模式）')

    # 工具选项
    tool_group = parser.add_argument_group('工具选项')
    tool_group.add_argument('--list-sources', action='store_true',
                            help='列出所有可用数据源')
    tool_group.add_argument('--validate', action='store_true',
                            help='验证数据质量（需先指定股票或CSV）')
    tool_group.add_argument('-v', '--version', action='version',
                            version=f'%(prog)s {__version__}')

    args = parser.parse_args()

    # 列出数据源
    if args.list_sources:
        list_datasources()
        return

    # CSV模式
    if args.csv:
        if not Path(args.csv).exists():
            print(f"错误: CSV文件不存在: {args.csv}")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  股票技术分析工具 v{__version__} - CSV模式")
        print(f"{'='*60}")

        analyzer = StockAnalyzer.from_csv(
            args.csv,
            stock_code=args.code,
            stock_name=args.name
        )

        if args.validate:
            show_data_quality(analyzer)
            return

        analyzer.generate_report(output_path=args.output, template_path=args.template)
        print("\n[OK] 分析完成!\n")
        return

    # 标准模式
    if not args.stock_code:
        print(f"\n{'='*60}")
        print(f"  股票技术分析工具 v{__version__}")
        print(f"{'='*60}")
        print("\n常见股票代码:")
        print("  600519 - 贵州茅台   600036 - 招商银行")
        print("  000001 - 平安银行   000858 - 五粮液")
        print("  601318 - 中国平安   601166 - 兴业银行")
        print(f"{'-'*60}\n")

        stock_code = input("请输入股票代码 (6位数字): ").strip()
    else:
        stock_code = args.stock_code

    # 验证股票代码
    if not stock_code or not stock_code.isdigit() or len(stock_code) != 6:
        print("错误: 股票代码必须是6位数字")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  股票技术分析工具 v{__version__}")
    print(f"{'='*60}")

    try:
        # 创建分析器
        if args.source == 'auto':
            analyzer = StockAnalyzer(stock_code)
        else:
            analyzer = StockAnalyzer.from_datasource(stock_code, args.source)

        # 验证数据质量
        if args.validate:
            analyzer.load_data(days=args.days)
            show_data_quality(analyzer)
            return

        # 生成报告
        report_path = analyzer.generate_report(
            output_path=args.output,
            template_path=args.template
        )

        print(f"\n{'='*60}")
        print(f"[OK] 分析完成!")
        print(f"  报告路径: {report_path}")
        print(f"{'='*60}\n")

    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[X] 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def list_datasources():
    """列出所有数据源"""
    from .config import DATASOURCE_CONFIG

    print(f"\n{'='*60}")
    print("  可用数据源")
    print(f"{'='*60}\n")

    for name, config in sorted(DATASOURCE_CONFIG.items(),
                               key=lambda x: x[1].get('priority', 999)):
        if name == 'csv':
            continue

        enabled = "[OK]" if config.get('enabled', False) else "[X]"
        priority = config.get('priority', 'N/A')
        print(f"{enabled} {name:15s} (优先级: {priority})")

        # 测试可用性
        try:
            # 使用测试代码 600519
            ds = DataSourceFactory.create(name, stock_code='600519')
            available = "可用" if ds.is_available() else "不可用"
            print(f"  状态: {available}")
        except Exception as e:
            print(f"  状态: 错误 ({e})")

        print()


def show_data_quality(analyzer: StockAnalyzer):
    """显示数据质量报告"""
    print("\n数据质量报告:")
    print("="*60)

    report = analyzer.get_data_quality_report()

    print(f"\n总行数: {report['total_rows']}")

    if report['date_range']:
        dr = report['date_range']
        print(f"日期范围: {dr['start']} 至 {dr['end']} ({dr['days']}天)")

    print("\n缺失值统计:")
    for col, count in report['missing_values'].items():
        if count > 0:
            print(f"  {col}: {count}")

    print("\n数值统计:")
    for col, stats in report['summary_stats'].items():
        if col in ['收盘', '成交量', '涨跌幅']:
            print(f"  {col}:")
            print(f"    均值: {stats['mean']:.2f}")
            print(f"    范围: [{stats['min']:.2f}, {stats['max']:.2f}]")

    print("="*60)


if __name__ == '__main__':
    main()
