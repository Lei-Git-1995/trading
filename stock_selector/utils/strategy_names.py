"""Built-in Chinese display names for strategy IDs."""

PRESET_DISPLAY_NAMES = {
    'default': '默认策略',
    'aggressive': '激进选股',
    'conservative': '保守选股',
    'dip_buying': '低吸反弹',
    'breakout': '放量突破',
    'mainboard_only': '主板稳健',
    'sector_rotation': '题材轮动',
    'value_return': '超跌价值回归',
    'limit_up_chase': '涨停追击',
    'big_order_500w': '大单流入（500万元）',
    'big_order_1000w': '大单流入（1000万元）',
    'big_order_5000w': '大单流入（5000万元）',
    'capital_grab': '主力资金抢筹',
    'violent_suppress': '放量打压洗盘',
}


def strategy_display_name(strategy_id, config=None, family='preset'):
    """Return a Chinese label, honoring names supplied by strategy config."""
    config = config or {}
    configured_name = config.get('display_name') or config.get('name')
    if configured_name:
        return str(configured_name)
    if family == 'preset':
        return PRESET_DISPLAY_NAMES.get(strategy_id, strategy_id)
    return strategy_id
