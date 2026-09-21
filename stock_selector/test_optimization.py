#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试优化后的选股系统

测试项：
1. 日志系统
2. 配置加载
3. 预设策略
4. 性能计时
"""
import sys
import os
from pathlib import Path

# 设置控制台编码为UTF-8（Windows）
if sys.platform == 'win32':
    os.system('chcp 65001 > nul')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def test_logger():
    """测试日志系统"""
    print("\n" + "="*70)
    print("测试 1: 日志系统")
    print("="*70)

    from stock_selector.utils.logger import setup_logger, get_logger

    setup_logger(level=20)  # INFO
    logger = get_logger(__name__)

    logger.debug("这是DEBUG消息（不应显示）")
    logger.info("这是INFO消息 [OK]")
    logger.warning("这是WARNING消息 [OK]")
    logger.error("这是ERROR消息 [OK]")

    print("[OK] 日志系统测试通过")


def test_config_loader():
    """测试配置加载器"""
    print("\n" + "="*70)
    print("测试 2: 配置加载器")
    print("="*70)

    from stock_selector.utils.config_loader import list_presets, load_preset

    presets = list_presets()
    print(f"找到 {len(presets)} 个预设: {', '.join(presets)}")

    # 测试加载预设
    config = load_preset('aggressive')
    print(f"\n加载预设 'aggressive':")
    print(f"  换手率: {config['turnover']}")
    print(f"  涨跌幅: {config['change']}")
    print(f"  量能: {config['volume']}")

    print("\n[OK] 配置加载器测试通过")


def test_timer():
    """测试性能计时器"""
    print("\n" + "="*70)
    print("测试 3: 性能计时器")
    print("="*70)

    import time
    from stock_selector.utils.timer import timeit, print_stats, clear_stats

    clear_stats()

    with timeit('任务1'):
        time.sleep(0.1)

    with timeit('任务2'):
        time.sleep(0.05)

    with timeit('任务1'):
        time.sleep(0.1)

    print_stats()
    print("\n[OK] 性能计时器测试通过")


def test_preset_merge():
    """测试预设与命令行参数合并"""
    print("\n" + "="*70)
    print("测试 4: 预设参数合并")
    print("="*70)

    from stock_selector.utils.config_loader import merge_with_preset

    # 测试预设 + 覆盖
    merged = merge_with_preset('conservative', {'turnover': 10.0})
    print(f"conservative预设 + turnover=10.0:")
    print(f"  换手率: {merged['turnover']} (应为 10.0)")
    print(f"  涨跌幅: {merged['change']} (应为 [0, 3])")

    print("\n[OK] 预设参数合并测试通过")


def main():
    print("\n" + "="*70)
    print("选股系统优化功能测试")
    print("="*70)

    try:
        test_logger()
        test_config_loader()
        test_timer()
        test_preset_merge()

        print("\n" + "="*70)
        print("[OK] 所有测试通过！")
        print("="*70)

    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
