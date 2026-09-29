"""快速测试 v2 架构

测试新架构的核心功能是否正常工作
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_selector.strategies.strategy_adapter import load_v2_strategy
from stock_selector.data.providers import create_provider
import pandas as pd


def test_v2_architecture():
    """测试 v2 架构基础功能"""

    print("=" * 70)
    print("v2 架构快速测试")
    print("=" * 70)

    # 1. 测试策略加载
    print("\n[1/4] 测试策略加载...")
    try:
        adapter = load_v2_strategy('ultra_short')
        print(f"  ✓ 策略加载成功: {adapter.strategy_config['name']}")
        print(f"    {adapter.strategy_config['description']}")
    except Exception as e:
        print(f"  ✗ 策略加载失败: {e}")
        return False

    # 2. 测试数据源
    print("\n[2/4] 测试数据源...")
    try:
        provider = create_provider('eastmoney')
        print("  ✓ 数据源创建成功")
    except Exception as e:
        print(f"  ✗ 数据源创建失败: {e}")
        return False

    # 3. 测试获取股票列表
    print("\n[3/4] 测试获取股票列表...")
    try:
        stock_list = provider.get_all_stocks()
        if stock_list is None or stock_list.empty:
            print("  ✗ 股票列表为空")
            return False
        print(f"  ✓ 获取成功: {len(stock_list)} 只股票")
    except Exception as e:
        print(f"  ✗ 获取股票列表失败: {e}")
        return False

    # 4. 测试策略运行（只测试前5只）
    print("\n[4/4] 测试策略运行（样本测试）...")
    try:
        # 取前5只股票做测试
        sample_stocks = stock_list.head(5)
        print(f"  测试样本: {len(sample_stocks)} 只")

        results = adapter.run(sample_stocks, provider)
        print(f"  ✓ 策略运行成功")
        print(f"  ✓ 筛选结果: {len(results)} 只通过")

        if results:
            print("\n样本结果:")
            for i, stock in enumerate(results[:3], 1):
                print(f"  {i}. {stock['code']} {stock['name']}")
                print(f"     得分: {stock['score']:.1f}分")
                if stock.get('signals'):
                    print(f"     信号: {', '.join(stock['signals'][:2])}")
    except Exception as e:
        print(f"  ✗ 策略运行失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 70)
    print("✓ v2 架构测试通过！")
    print("=" * 70)
    print("\n现在可以运行完整选股:")
    print("  py -3.11 -m stock_selector.main --preset-v2 ultra_short")
    print("  py -3.11 -m stock_selector.main --preset-v2 momentum_start")
    print("  py -3.11 -m stock_selector.main --preset-v2 weak_to_strong")

    return True


if __name__ == '__main__':
    success = test_v2_architecture()
    sys.exit(0 if success else 1)
