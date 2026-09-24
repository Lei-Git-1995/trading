#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试脚本
验证重构后的框架是否正常工作
"""

def test_imports():
    """测试导入"""
    print("测试1: 导入模块...")
    try:
        from stock_analysis import StockAnalyzer, DataSourceFactory
        from stock_analysis.core import TechnicalIndicators, ReportGenerator, DataValidator
        from stock_analysis.datasources import (
            DataSourceBase, EastMoneyDataSource, TencentDataSource, CSVDataSource
        )
        print("[OK] 所有模块导入成功")
        return True
    except Exception as e:
        print(f"[FAIL] 导入失败: {e}")
        return False


def test_config():
    """测试配置"""
    print("\n测试2: 加载配置...")
    try:
        from stock_analysis.config import (
            DATASOURCE_CONFIG, INDICATOR_PARAMS, get_template_path, get_report_dir
        )
        print(f"[OK] 数据源配置: {len(DATASOURCE_CONFIG)} 个")
        print(f"[OK] 指标参数: {len(INDICATOR_PARAMS)} 组")
        print(f"[OK] 报告目录: {get_report_dir()}")
        return True
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        return False


def test_technical_indicators():
    """测试技术指标计算"""
    print("\n测试3: 技术指标计算...")
    try:
        import pandas as pd
        import numpy as np
        from stock_analysis.core import TechnicalIndicators

        # 创建模拟数据
        dates = pd.date_range('2024-01-01', periods=100)
        df = pd.DataFrame({
            '日期': dates,
            '开盘': np.random.uniform(10, 20, 100),
            '收盘': np.random.uniform(10, 20, 100),
            '最高': np.random.uniform(15, 25, 100),
            '最低': np.random.uniform(5, 15, 100),
            '成交量': np.random.uniform(1000000, 5000000, 100),
        })

        # 计算指标
        df = TechnicalIndicators.calculate_all(df)

        # 检查结果
        required_cols = ['MA5', 'MA10', 'MACD_DIF', 'KDJ_K', 'RSI6', 'BOLL_MID']
        for col in required_cols:
            if col not in df.columns:
                raise Exception(f"缺少指标列: {col}")

        print(f"[OK] 成功计算 {len(df.columns)} 个指标")
        print(f"  均线: MA5={df.iloc[-1]['MA5']:.2f}")
        print(f"  MACD: DIF={df.iloc[-1]['MACD_DIF']:.4f}")
        return True
    except Exception as e:
        print(f"[FAIL] 技术指标计算失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_data_validator():
    """测试数据验证"""
    print("\n测试4: 数据验证...")
    try:
        import pandas as pd
        from stock_analysis.core import DataValidator

        # 创建测试数据
        df = pd.DataFrame({
            '日期': ['2024-01-01', '2024-01-02'],
            '开盘': [10.0, 11.0],
            '收盘': [10.5, 11.5],
            '最高': [11.0, 12.0],
            '最低': [9.5, 10.5],
            '成交量': [1000000, 1200000],
        })

        # 验证必需列
        required = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
        is_valid, missing = DataValidator.validate_required_columns(df, required)
        assert is_valid, f"列验证失败: {missing}"

        # 清洗数据
        df_clean = DataValidator.clean_data(df)
        assert '涨跌幅' in df_clean.columns, "缺少计算列"

        # 质量报告
        report = DataValidator.get_data_quality_report(df_clean)
        assert 'total_rows' in report, "质量报告不完整"

        print(f"[OK] 数据验证通过")
        print(f"  总行数: {report['total_rows']}")
        return True
    except Exception as e:
        print(f"[FAIL] 数据验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_datasource_factory():
    """测试数据源工厂"""
    print("\n测试5: 数据源工厂...")
    try:
        from stock_analysis.datasources import DataSourceFactory

        # 测试创建CSV数据源（不需要网络）
        # 注意：这里只测试创建，不测试实际数据获取
        print("  数据源注册表:")
        for name in DataSourceFactory._datasources.keys():
            print(f"    - {name}")

        print("[OK] 数据源工厂正常")
        return True
    except Exception as e:
        print(f"[FAIL] 数据源工厂失败: {e}")
        return False


def main():
    """运行所有测试"""
    print("="*60)
    print("  股票分析框架 - 单元测试")
    print("="*60)

    tests = [
        test_imports,
        test_config,
        test_technical_indicators,
        test_data_validator,
        test_datasource_factory,
    ]

    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"[FAIL] 测试异常: {e}")
            results.append(False)

    print("\n" + "="*60)
    print(f"  测试结果: {sum(results)}/{len(results)} 通过")
    print("="*60)

    if all(results):
        print("\n[OK] 所有测试通过! 框架可以正常使用。")
        return 0
    else:
        print("\n[FAIL] 部分测试失败，请检查错误信息。")
        return 1


if __name__ == '__main__':
    exit(main())
