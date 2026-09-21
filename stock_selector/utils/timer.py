"""
性能计时器：统计各阶段执行时间

用法：
    from stock_selector.utils.timer import Timer

    with Timer('获取行情') as t:
        # 执行操作
        pass

    print(f'耗时: {t.elapsed:.2f}秒')

    # 或使用全局统计
    from stock_selector.utils.timer import timeit, get_stats, print_stats

    @timeit('数据处理')
    def process_data():
        pass

    process_data()
    print_stats()
"""
import time
from contextlib import contextmanager
from typing import Dict, List
from collections import defaultdict


class Timer:
    """计时器上下文管理器"""

    def __init__(self, name: str = None):
        self.name = name
        self.start_time = None
        self.end_time = None
        self.elapsed = 0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.elapsed = self.end_time - self.start_time
        return False


# 全局计时统计
_global_stats: Dict[str, List[float]] = defaultdict(list)


def record_time(name: str, elapsed: float):
    """记录一次计时"""
    _global_stats[name].append(elapsed)


def get_stats() -> Dict[str, Dict[str, float]]:
    """
    获取统计信息

    Returns:
        {
            '阶段名': {
                'count': 调用次数,
                'total': 总耗时,
                'avg': 平均耗时,
                'min': 最小耗时,
                'max': 最大耗时
            }
        }
    """
    stats = {}
    for name, times in _global_stats.items():
        if times:
            stats[name] = {
                'count': len(times),
                'total': sum(times),
                'avg': sum(times) / len(times),
                'min': min(times),
                'max': max(times),
            }
    return stats


def clear_stats():
    """清除统计数据"""
    _global_stats.clear()


def print_stats():
    """打印统计信息"""
    stats = get_stats()
    if not stats:
        print('无性能统计数据')
        return

    print('\n' + '=' * 70)
    print('性能统计')
    print('=' * 70)

    # 按总耗时排序
    sorted_stats = sorted(stats.items(), key=lambda x: x[1]['total'], reverse=True)

    for name, data in sorted_stats:
        count = data['count']
        total = data['total']
        avg = data['avg']

        if count == 1:
            print(f'{name:30s}: {total:8.2f}秒')
        else:
            print(f'{name:30s}: {total:8.2f}秒 (平均 {avg:.2f}秒 × {count}次)')

    print('=' * 70)


@contextmanager
def timeit(name: str, record: bool = True):
    """
    计时上下文管理器（自动记录到全局统计）

    Args:
        name: 阶段名称
        record: 是否记录到全局统计

    用法：
        with timeit('数据处理'):
            process()
    """
    start = time.time()
    yield
    elapsed = time.time() - start

    if record:
        record_time(name, elapsed)


def format_time(seconds: float) -> str:
    """
    格式化时间显示

    Args:
        seconds: 秒数

    Returns:
        格式化的字符串（如 "1分23秒"、"45.2秒"）
    """
    if seconds < 60:
        return f'{seconds:.1f}秒'
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f'{minutes}分{secs:.0f}秒'
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f'{hours}小时{minutes}分'
