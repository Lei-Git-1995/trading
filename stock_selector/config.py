"""全局配置：筛选参数与路径"""
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / 'output'
CACHE_DIR = PROJECT_ROOT / 'data' / '.cache'


@dataclass
class ScreenerConfig:
    """短线选股筛选参数（默认值与原 daily_stock_picker.py 一致）"""

    # 筛选条件
    turnover_min: float = 15.0      # 最低换手率（%）
    change_min: float = 1.0         # 最低涨跌幅（%）
    change_max: float = 3.0         # 最高涨跌幅（%）
    volume_ratio: float = 1.3       # 量能放大倍数（相对前两日平均）
    top_per_sector: int = 20        # 每个板块最多选取数量（0 表示不限制）
    check_outer_inner: bool = True  # 是否检查外盘>内盘（True=要求外盘>内盘）
    check_kdj: bool = True          # 是否检查KDJ未超买（K<80）
    check_rsi: bool = True          # 是否检查RSI未超买（RSI6<70）
    filter_cyb: bool = False        # 是否过滤创业板（3开头）
    filter_kcb: bool = False        # 是否过滤科创板（688开头）

    # 数据行为
    history_days: int = 10          # 历史K线取几天（≥10确保腾讯回退通道滞后1天仍有当日数据）
    request_sleep: float = 0.3      # 历史数据请求间隔（秒）
    cache_ttl_hours: float = 8.0    # K线缓存有效期（小时）

    # 输出
    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)


def build_config(**overrides) -> ScreenerConfig:
    """按显式参数覆盖默认配置"""
    return ScreenerConfig(**{k: v for k, v in overrides.items() if v is not None})