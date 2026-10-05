"""
智能数据源管理器

功能:
1. 自动选择最佳数据源
2. 失败时自动切换到备用源
3. 健康检查和容灾
"""
from __future__ import annotations

import time
from typing import Optional, List, Tuple
from pathlib import Path

from stock_selector.data.providers import create_provider, list_providers, DataProvider
from stock_selector.data.provider_health_monitor import ProviderHealthMonitor, ProviderHealth
from stock_selector.utils.logger import get_logger

logger = get_logger(__name__)


class SmartProviderManager:
    """智能数据源管理器"""

    def __init__(self, preferred_provider: Optional[str] = None):
        """
        Args:
            preferred_provider: 优先使用的数据源（如果可用）
        """
        self.preferred_provider = preferred_provider
        self.monitor = ProviderHealthMonitor()
        self.current_provider: Optional[DataProvider] = None
        self.current_provider_name: Optional[str] = None
        self.provider_queue: List[str] = []
        self.failed_providers: set = set()

    def _build_provider_queue(self) -> List[str]:
        """
        构建数据源优先级队列

        Returns:
            数据源名称列表（按优先级排序）
        """
        # 获取最近的健康状态
        all_providers = list_providers()
        provider_scores = []

        for provider_name, display_name in all_providers:
            # 从历史记录中获取成功率
            history = self.monitor.history.get(provider_name, [])
            if not history:
                # 没有历史记录，给予中等评分
                score = 50.0
            else:
                # 只看最近10次
                recent = history[-10:]
                success_count = sum(1 for h in recent if h['available'])
                success_rate = (success_count / len(recent)) * 100

                # 获取平均响应时间
                response_times = [h['response_time'] for h in recent if h['available']]
                avg_response = sum(response_times) / len(response_times) if response_times else 10.0

                # 计算综合评分：成功率权重80%，响应时间权重20%
                # 响应时间转换为分数（越快越高，10秒为基准）
                response_score = max(0, 100 - (avg_response / 10.0) * 100)
                score = success_rate * 0.8 + response_score * 0.2

            provider_scores.append((provider_name, score))

        # 按评分排序
        provider_scores.sort(key=lambda x: -x[1])

        # 优先使用用户指定的数据源（如果可用）
        queue = []
        if self.preferred_provider:
            queue.append(self.preferred_provider)

        # 添加其他数据源
        for provider_name, score in provider_scores:
            if provider_name not in queue:
                queue.append(provider_name)

        return queue

    def get_provider(self, force_refresh: bool = False) -> Optional[DataProvider]:
        """
        获取可用的数据源实例

        Args:
            force_refresh: 是否强制刷新（重新测试）

        Returns:
            数据源实例，如果所有数据源都不可用则返回None
        """
        # 如果已有可用的数据源且不强制刷新，直接返回
        if self.current_provider and not force_refresh:
            return self.current_provider

        # 构建优先级队列
        if not self.provider_queue or force_refresh:
            self.provider_queue = self._build_provider_queue()
            self.failed_providers.clear()

        logger.info(f"数据源优先级队列: {', '.join(self.provider_queue)}")

        # 尝试每个数据源
        for provider_name in self.provider_queue:
            # 跳过已失败的数据源
            if provider_name in self.failed_providers:
                continue

            try:
                logger.info(f"尝试连接数据源: {provider_name}")
                start_time = time.time()

                # 创建数据源实例
                provider = create_provider(provider_name)

                # 快速健康检查：获取股票列表
                stock_list = provider.get_all_stocks()
                elapsed = time.time() - start_time

                if stock_list is None or stock_list.empty or len(stock_list) < 10:
                    logger.warning(f"  数据源 {provider_name} 返回数据异常")
                    self.failed_providers.add(provider_name)
                    continue

                # 成功！
                self.current_provider = provider
                self.current_provider_name = provider_name

                logger.info(f"  ✓ 连接成功！({elapsed:.2f}秒)")
                logger.info(f"  当前使用: {provider_name}")

                return provider

            except Exception as e:
                logger.warning(f"  数据源 {provider_name} 连接失败: {e}")
                self.failed_providers.add(provider_name)
                continue

        # 所有数据源都失败
        logger.error("所有数据源均不可用！")
        return None

    def switch_provider(self) -> Optional[DataProvider]:
        """
        切换到下一个可用的数据源

        Returns:
            新的数据源实例，如果没有可用的则返回None
        """
        logger.info("切换数据源...")

        # 标记当前数据源为失败
        if self.current_provider_name:
            self.failed_providers.add(self.current_provider_name)

        # 重置当前数据源
        self.current_provider = None
        self.current_provider_name = None

        # 获取下一个可用的数据源
        return self.get_provider()

    def execute_with_retry(self, func, *args, max_retries: int = 3, **kwargs):
        """
        执行函数，失败时自动切换数据源重试

        Args:
            func: 要执行的函数（需要接受provider作为第一个参数）
            max_retries: 最大重试次数
            *args, **kwargs: 传递给函数的参数

        Returns:
            函数执行结果

        Raises:
            Exception: 所有数据源都失败后抛出异常
        """
        last_error = None

        for retry in range(max_retries):
            provider = self.get_provider()
            if provider is None:
                raise Exception("没有可用的数据源")

            try:
                # 执行函数
                result = func(provider, *args, **kwargs)
                return result

            except Exception as e:
                last_error = e
                logger.warning(f"数据源 {self.current_provider_name} 执行失败: {e}")

                # 如果还有重试次数，切换数据源
                if retry < max_retries - 1:
                    logger.info(f"第 {retry + 1}/{max_retries} 次重试...")
                    self.switch_provider()
                else:
                    logger.error("所有重试均失败")

        # 所有重试都失败
        raise Exception(f"执行失败，已尝试 {max_retries} 次: {last_error}")


# 全局单例
_global_manager: Optional[SmartProviderManager] = None


def get_smart_provider(preferred: Optional[str] = None) -> SmartProviderManager:
    """
    获取全局智能数据源管理器

    Args:
        preferred: 优先使用的数据源

    Returns:
        SmartProviderManager实例
    """
    global _global_manager

    if _global_manager is None:
        _global_manager = SmartProviderManager(preferred)

    return _global_manager


def auto_select_provider() -> str:
    """
    自动选择最佳数据源

    Returns:
        数据源名称
    """
    monitor = ProviderHealthMonitor()

    # 从历史记录中选择
    best = monitor.get_best_provider()

    if best:
        logger.info(f"自动选择数据源: {best}")
        return best

    # 没有历史记录，运行快速测试
    logger.info("没有历史记录，运行快速测试...")
    results = monitor.test_all_providers(timeout=10)
    best = monitor.get_best_provider(results)

    if best:
        return best

    # 实在没有，返回默认值
    logger.warning("无法确定最佳数据源，使用默认: tencent")
    return "tencent"


if __name__ == '__main__':
    # 测试自动选择
    print("测试智能数据源管理器")
    print("=" * 70)

    manager = SmartProviderManager()
    provider = manager.get_provider()

    if provider:
        print(f"\n✓ 成功获取数据源: {manager.current_provider_name}")

        # 测试获取股票列表
        stocks = provider.get_all_stocks()
        print(f"✓ 股票数量: {len(stocks)}")

        # 测试切换
        print("\n测试切换数据源...")
        provider2 = manager.switch_provider()
        if provider2:
            print(f"✓ 切换成功: {manager.current_provider_name}")
    else:
        print("\n✗ 没有可用的数据源")

    print("\n" + "=" * 70)
