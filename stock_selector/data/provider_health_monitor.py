"""
数据源健康监控系统

功能:
1. 测试所有数据提供商的连通性
2. 监控响应时间和成功率
3. 生成健康报告
4. 提供数据源排序（按可靠性）
"""

import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

from stock_selector.data.providers import create_provider, list_providers
from stock_selector.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProviderHealth:
    """数据源健康状态"""
    name: str
    display_name: str
    available: bool
    response_time: float  # 秒
    success_rate: float  # 百分比
    last_test_time: str
    last_success_time: Optional[str]
    last_error: Optional[str]
    test_count: int
    success_count: int
    fail_count: int
    avg_response_time: float

    def to_dict(self) -> Dict:
        return asdict(self)


class ProviderHealthMonitor:
    """数据源健康监控器"""

    def __init__(self, history_file: Optional[Path] = None):
        """
        Args:
            history_file: 历史记录文件路径
        """
        if history_file is None:
            history_file = Path(__file__).parent.parent / 'data' / 'provider_health.json'

        self.history_file = history_file
        self.history: Dict[str, List[Dict]] = self._load_history()

    def _load_history(self) -> Dict[str, List[Dict]]:
        """加载历史记录"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载历史记录失败: {e}")

        return defaultdict(list)

    def _save_history(self):
        """保存历史记录"""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史记录失败: {e}")

    def test_provider(self, provider_name: str, timeout: int = 10) -> Tuple[bool, float, Optional[str]]:
        """
        测试单个数据源

        Args:
            provider_name: 数据源名称
            timeout: 超时时间（秒）

        Returns:
            (是否可用, 响应时间, 错误信息)
        """
        try:
            start_time = time.time()

            # 创建数据源实例
            provider = create_provider(provider_name)

            # 测试获取股票列表（只取前10条，减少测试时间）
            stock_list = provider.get_all_stocks()

            elapsed = time.time() - start_time

            if stock_list is None or stock_list.empty:
                return False, elapsed, "返回数据为空"

            if len(stock_list) < 10:
                return False, elapsed, f"数据量异常: 只有{len(stock_list)}条"

            # 测试获取K线数据
            sample_code = stock_list['code'].iloc[0]
            hist = provider.get_stock_history(sample_code, days=5)

            elapsed = time.time() - start_time

            if hist is None or hist.empty:
                return False, elapsed, "K线数据获取失败"

            return True, elapsed, None

        except Exception as e:
            elapsed = time.time() - start_time
            return False, elapsed, str(e)

    def test_all_providers(self, timeout: int = 10) -> Dict[str, ProviderHealth]:
        """
        测试所有数据源

        Args:
            timeout: 单个数据源的超时时间

        Returns:
            数据源健康状态字典
        """
        results = {}
        providers = list_providers()

        logger.info(f"开始测试 {len(providers)} 个数据源...")

        for provider_name, display_name in providers:
            logger.info(f"\n测试数据源: {display_name} ({provider_name})")

            # 测试数据源
            available, response_time, error = self.test_provider(provider_name, timeout)

            # 获取历史统计
            history = self.history.get(provider_name, [])
            test_count = len(history) + 1
            success_count = sum(1 for h in history if h['available']) + (1 if available else 0)
            fail_count = test_count - success_count
            success_rate = (success_count / test_count) * 100 if test_count > 0 else 0

            # 计算平均响应时间
            response_times = [h['response_time'] for h in history if h['available']]
            if available:
                response_times.append(response_time)
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0

            # 获取最后成功时间
            last_success_time = None
            if available:
                last_success_time = datetime.now().isoformat()
            else:
                for h in reversed(history):
                    if h['available']:
                        last_success_time = h['test_time']
                        break

            # 创建健康状态
            health = ProviderHealth(
                name=provider_name,
                display_name=display_name,
                available=available,
                response_time=response_time,
                success_rate=success_rate,
                last_test_time=datetime.now().isoformat(),
                last_success_time=last_success_time,
                last_error=error,
                test_count=test_count,
                success_count=success_count,
                fail_count=fail_count,
                avg_response_time=avg_response_time
            )

            results[provider_name] = health

            # 记录到历史
            self.history[provider_name].append({
                'test_time': health.last_test_time,
                'available': available,
                'response_time': response_time,
                'error': error
            })

            # 只保留最近100次记录
            if len(self.history[provider_name]) > 100:
                self.history[provider_name] = self.history[provider_name][-100:]

            # 输出结果
            status_icon = "✓" if available else "✗"
            logger.info(f"  状态: {status_icon} {'可用' if available else '不可用'}")
            logger.info(f"  响应时间: {response_time:.2f}秒")
            logger.info(f"  成功率: {success_rate:.1f}% ({success_count}/{test_count})")
            if error:
                logger.info(f"  错误: {error}")

        # 保存历史记录
        self._save_history()

        return results

    def get_best_provider(self, results: Optional[Dict[str, ProviderHealth]] = None) -> Optional[str]:
        """
        获取最佳数据源

        优先级:
        1. 当前可用
        2. 成功率高
        3. 响应时间短

        Args:
            results: 测试结果（如果为None，则使用历史数据）

        Returns:
            最佳数据源名称
        """
        if results is None:
            # 从历史数据中获取
            results = {}
            for provider_name, display_name in list_providers():
                history = self.history.get(provider_name, [])
                if not history:
                    continue

                recent = history[-10:]  # 最近10次
                success_count = sum(1 for h in recent if h['available'])
                success_rate = (success_count / len(recent)) * 100

                last = recent[-1]
                results[provider_name] = ProviderHealth(
                    name=provider_name,
                    display_name=display_name,
                    available=last['available'],
                    response_time=last['response_time'],
                    success_rate=success_rate,
                    last_test_time=last['test_time'],
                    last_success_time=None,
                    last_error=last.get('error'),
                    test_count=len(history),
                    success_count=success_count,
                    fail_count=len(recent) - success_count,
                    avg_response_time=0
                )

        # 筛选可用的数据源
        available_providers = [
            (name, health) for name, health in results.items()
            if health.available
        ]

        if not available_providers:
            logger.warning("没有可用的数据源！")
            return None

        # 按优先级排序: 成功率 > 响应时间
        sorted_providers = sorted(
            available_providers,
            key=lambda x: (-x[1].success_rate, x[1].response_time)
        )

        best_name, best_health = sorted_providers[0]
        logger.info(f"\n推荐数据源: {best_health.display_name} ({best_name})")
        logger.info(f"  成功率: {best_health.success_rate:.1f}%")
        logger.info(f"  响应时间: {best_health.response_time:.2f}秒")

        return best_name

    def generate_report(self, results: Dict[str, ProviderHealth], output_file: Optional[Path] = None) -> str:
        """
        生成健康报告

        Args:
            results: 测试结果
            output_file: 输出文件路径

        Returns:
            报告内容
        """
        report_lines = [
            "# 数据源健康报告",
            "",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**测试数量**: {len(results)} 个数据源",
            "",
            "---",
            "",
            "## 📊 综合评分",
            ""
        ]

        # 按综合评分排序
        sorted_results = sorted(
            results.items(),
            key=lambda x: (
                -x[1].available,  # 可用性优先
                -x[1].success_rate,  # 成功率
                x[1].response_time  # 响应时间
            )
        )

        # 评分表格
        report_lines.extend([
            "| 排名 | 数据源 | 状态 | 响应时间 | 成功率 | 测试次数 | 推荐度 |",
            "|------|--------|------|----------|--------|----------|--------|"
        ])

        for rank, (name, health) in enumerate(sorted_results, 1):
            status = "✓ 可用" if health.available else "✗ 不可用"
            response = f"{health.response_time:.2f}s"
            success_rate = f"{health.success_rate:.1f}%"
            tests = f"{health.success_count}/{health.test_count}"

            # 计算推荐度
            if not health.available:
                recommend = "❌"
            elif health.success_rate >= 90 and health.response_time < 3:
                recommend = "⭐⭐⭐"
            elif health.success_rate >= 70 and health.response_time < 5:
                recommend = "⭐⭐"
            elif health.success_rate >= 50:
                recommend = "⭐"
            else:
                recommend = "⚠️"

            report_lines.append(
                f"| {rank} | {health.display_name} | {status} | {response} | {success_rate} | {tests} | {recommend} |"
            )

        report_lines.extend([
            "",
            "---",
            "",
            "## 📝 详细信息",
            ""
        ])

        # 详细信息
        for name, health in sorted_results:
            status_icon = "✓" if health.available else "✗"
            report_lines.extend([
                f"### {status_icon} {health.display_name} ({name})",
                "",
                f"- **当前状态**: {'可用' if health.available else '不可用'}",
                f"- **响应时间**: {health.response_time:.2f}秒",
                f"- **平均响应**: {health.avg_response_time:.2f}秒",
                f"- **成功率**: {health.success_rate:.1f}% ({health.success_count}成功/{health.fail_count}失败)",
                f"- **测试次数**: {health.test_count}",
                f"- **最后测试**: {health.last_test_time}",
            ])

            if health.last_success_time:
                report_lines.append(f"- **最后成功**: {health.last_success_time}")

            if health.last_error:
                report_lines.extend([
                    f"- **错误信息**: {health.last_error}",
                ])

            report_lines.append("")

        report_lines.extend([
            "---",
            "",
            "## 💡 使用建议",
            "",
            "### 推荐数据源",
            ""
        ])

        # 推荐列表
        available = [h for h in sorted_results if h[1].available]
        if available:
            report_lines.append("按优先级使用:")
            for i, (name, health) in enumerate(available[:3], 1):
                report_lines.append(
                    f"{i}. **{health.display_name}** - "
                    f"成功率{health.success_rate:.1f}%, "
                    f"响应{health.response_time:.2f}s"
                )
        else:
            report_lines.append("⚠️ 当前没有可用的数据源！")

        report_lines.extend([
            "",
            "### 自动切换策略",
            "",
            "系统将按以下顺序自动切换:",
            "1. 优先使用成功率最高的数据源",
            "2. 失败时自动切换到备用数据源",
            "3. 所有数据源失败时报错",
            "",
            "---",
            "",
            f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
        ])

        report_content = "\n".join(report_lines)

        # 保存到文件
        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_content)
            logger.info(f"\n健康报告已保存: {output_file}")

        return report_content


def test_all_providers_cli():
    """命令行测试入口"""
    print("=" * 70)
    print("数据源健康测试")
    print("=" * 70)

    monitor = ProviderHealthMonitor()
    results = monitor.test_all_providers(timeout=15)

    # 生成报告
    report_file = Path(__file__).parent.parent / 'output' / 'provider_health_report.md'
    monitor.generate_report(results, report_file)

    # 推荐最佳数据源
    print("\n" + "=" * 70)
    best = monitor.get_best_provider(results)
    if best:
        print(f"推荐使用: {best}")
    else:
        print("警告: 没有可用的数据源！")
    print("=" * 70)


if __name__ == '__main__':
    test_all_providers_cli()
