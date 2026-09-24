#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试新框架的简单示例
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock_analysis import StockAnalyzer
from stock_analysis.core import TechnicalIndicators
import pandas as pd
import numpy as np


def demo_technical_indicators():
    """演示技术指标计算"""
    print("="*60)
    print("  示例1: 技术指标计算")
    print("="*60)

    # 创建模拟数据
    dates = pd.date_range('2024-01-01', periods=100)
    df = pd.DataFrame({
        '日期': dates,
        '开盘': np.random.uniform(100, 110, 100),
        '收盘': np.random.uniform(100, 110, 100),
        '最高': np.random.uniform(105, 115, 100),
        '最低': np.random.uniform(95, 105, 100),
        '成交量': np.random.uniform(1000000, 5000000, 100),
    })

    print(f"\n原始数据: {len(df)} 行")
    print(df.head())

    # 计算技术指标
    df = TechnicalIndicators.calculate_all(df)

    print(f"\n添加技术指标后: {len(df.columns)} 列")
    print(f"新增列: {[col for col in df.columns if col not in ['日期', '开盘', '收盘', '最高', '最低', '成交量']]}")

    # 显示最新指标值
    latest = df.iloc[-1]
    print(f"\n最新指标值:")
    print(f"  MA5:  {latest['MA5']:.2f}")
    print(f"  MA10: {latest['MA10']:.2f}")
    print(f"  MA20: {latest['MA20']:.2f}")
    print(f"  MACD_DIF: {latest['MACD_DIF']:.4f}")
    print(f"  MACD_DEA: {latest['MACD_DEA']:.4f}")
    print(f"  KDJ_K: {latest['KDJ_K']:.2f}")
    print(f"  RSI6:  {latest['RSI6']:.2f}")
    print(f"  BOLL_UPPER: {latest['BOLL_UPPER']:.2f}")
    print(f"  BOLL_LOWER: {latest['BOLL_LOWER']:.2f}")

    # 趋势分析
    analysis = TechnicalIndicators.analyze_trend(df)
    print(f"\n趋势分析:")
    print(f"  均线排列: {analysis['trend']}")
    print(f"  MACD信号: {analysis['macd_signal']} ({analysis['macd_status']})")
    print(f"  KDJ状态: {analysis['kdj_status']}")
    print(f"  RSI状态: {analysis['rsi_status']}")


def demo_csv_analysis():
    """演示CSV分析"""
    print("\n" + "="*60)
    print("  示例2: CSV数据分析")
    print("="*60)

    # 创建临时CSV文件
    csv_file = 'test_stock_data.csv'
    dates = pd.date_range('2024-01-01', periods=60)
    df = pd.DataFrame({
        '日期': dates.strftime('%Y-%m-%d'),
        '开盘': np.random.uniform(100, 110, 60),
        '收盘': np.random.uniform(100, 110, 60),
        '最高': np.random.uniform(105, 115, 60),
        '最低': np.random.uniform(95, 105, 60),
        '成交量': np.random.uniform(1000000, 5000000, 60),
        '成交额': np.random.uniform(100000000, 500000000, 60),
    })
    df.to_csv(csv_file, index=False, encoding='utf-8-sig')
    print(f"\n已创建测试CSV: {csv_file}")

    try:
        # 从CSV创建分析器
        analyzer = StockAnalyzer.from_csv(csv_file, '600519', '测试股票')
        print(f"成功创建分析器")

        # 加载数据
        data = analyzer.load_data()
        print(f"成功加载 {len(data)} 条数据")

        # 计算指标
        analyzer.calculate_indicators()
        print(f"成功计算技术指标")

        # 分析
        analysis = analyzer.analyze()
        print(f"\n分析结果:")
        print(f"  趋势: {analysis['trend']}")
        print(f"  MACD: {analysis['macd_status']}")

    finally:
        # 清理临时文件
        if os.path.exists(csv_file):
            os.remove(csv_file)
            print(f"\n已删除测试文件")


def demo_data_source_factory():
    """演示数据源工厂"""
    print("\n" + "="*60)
    print("  示例3: 数据源工厂")
    print("="*60)

    from stock_analysis.datasources import DataSourceFactory

    print("\n已注册的数据源:")
    for name in DataSourceFactory._datasources.keys():
        print(f"  - {name}")

    print("\n数据源配置:")
    from stock_analysis.config import DATASOURCE_CONFIG
    for name, config in DATASOURCE_CONFIG.items():
        enabled = "启用" if config.get('enabled', False) else "禁用"
        priority = config.get('priority', 'N/A')
        print(f"  {name:15s} - {enabled:4s} (优先级: {priority})")


def main():
    """运行所有示例"""
    print("\n")
    print("#" * 60)
    print("#  股票分析框架 v2.0 - 功能演示")
    print("#" * 60)

    try:
        demo_technical_indicators()
        demo_csv_analysis()
        demo_data_source_factory()

        print("\n" + "="*60)
        print("  所有示例运行完成!")
        print("="*60)
        print("\n提示: 运行实际股票分析:")
        print("  python -m stock_analysis 600519")
        print("  python scripts/analyze_stock.py 600519")
        print("")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
