"""
配置加载器：从 YAML 文件加载预设配置

用法：
    from stock_selector.utils.config_loader import load_preset, list_presets

    # 列出所有预设
    presets = list_presets()

    # 加载预设
    config = load_preset('aggressive')
"""
import yaml
from pathlib import Path
from typing import Dict, Any, List


def get_presets_file() -> Path:
    """获取预设配置文件路径"""
    from stock_selector.config import PROJECT_ROOT
    return PROJECT_ROOT / 'presets.yaml'


def load_presets_file() -> Dict[str, Any]:
    """加载预设配置文件"""
    presets_file = get_presets_file()

    if not presets_file.exists():
        return {'presets': {}}

    try:
        with open(presets_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data if data else {'presets': {}}
    except Exception as e:
        raise RuntimeError(f'无法加载预设配置文件 {presets_file}: {e}')


def list_presets() -> List[str]:
    """列出所有可用的预设名称"""
    data = load_presets_file()
    return list(data.get('presets', {}).keys())


def get_preset(name: str) -> Dict[str, Any]:
    """
    获取指定名称的预设配置

    Args:
        name: 预设名称

    Returns:
        预设配置字典

    Raises:
        ValueError: 预设不存在
    """
    data = load_presets_file()
    presets = data.get('presets', {})

    if name not in presets:
        available = ', '.join(presets.keys()) if presets else '无'
        raise ValueError(f'预设 "{name}" 不存在。可用预设: {available}')

    return presets[name]


def load_preset(name: str) -> Dict[str, Any]:
    """
    加载预设配置（别名，同 get_preset）

    Args:
        name: 预设名称

    Returns:
        预设配置字典
    """
    return get_preset(name)


def merge_with_preset(preset_name: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    将预设配置与命令行覆盖参数合并

    Args:
        preset_name: 预设名称
        overrides: 命令行参数覆盖字典

    Returns:
        合并后的配置字典（命令行参数优先）
    """
    preset = get_preset(preset_name)

    # 创建合并后的配置
    merged = preset.copy()

    # 命令行参数覆盖预设
    for key, value in overrides.items():
        if value is not None:
            merged[key] = value

    return merged


def print_preset_info(name: str) -> None:
    """
    打印预设配置信息

    Args:
        name: 预设名称
    """
    import sys

    # 确保控制台输出使用UTF-8编码
    if sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    preset = get_preset(name)

    print(f'\n预设策略: {name}')
    print('-' * 50)

    # 格式化输出配置项
    key_labels = {
        'turnover': '换手率',
        'change': '涨跌幅区间',
        'volume': '量能倍数',
        'sector': '板块限制',
        'check_outer_inner': '检查外盘>内盘',
        'check_kdj': '检查KDJ未超买',
        'check_rsi': '检查RSI未超买',
        'filter_cyb': '过滤创业板',
        'filter_kcb': '过滤科创板',
        'mainboard_only': '只选主板',
    }

    for key, label in key_labels.items():
        if key in preset:
            value = preset[key]
            if isinstance(value, list):
                value = f'{value[0]}% ~ {value[1]}%'
            elif isinstance(value, bool):
                value = '是' if value else '否'
            elif key == 'turnover':
                value = f'> {value}%'
            elif key == 'volume':
                value = f'> {value}倍'
            elif key == 'sector':
                value = f'每板块最多{value}只' if value > 0 else '不限制'

            print(f'{label:16s}: {value}')

    print('-' * 50)
