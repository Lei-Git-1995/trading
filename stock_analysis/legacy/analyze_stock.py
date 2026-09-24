#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速启动脚本
用于替代原来的独立脚本
"""

import sys
from stock_analysis import StockAnalyzer


def main():
    """主函数"""
    print("=" * 60)
    print("     股票技术分析报告生成器 (重构版)")
    print("=" * 60)
    print("\n常见股票代码:")
    print("  600519 - 贵州茅台   600036 - 招商银行")
    print("  000001 - 平安银行   000858 - 五粮液")
    print("  601318 - 中国平安")
    print("-" * 60)

    if len(sys.argv) >= 2:
        stock_code = sys.argv[1]
    else:
        stock_code = input("\n请输入股票代码 (6位数字): ").strip()

    if not stock_code or not stock_code.isdigit() or len(stock_code) != 6:
        print("错误: 股票代码必须是6位数字")
        sys.exit(1)

    try:
        # 使用重构后的分析器
        analyzer = StockAnalyzer(stock_code)
        analyzer.generate_report()
        print("\n✓ 分析完成!")

    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
