# -*- coding: utf-8 -*-
"""LLM 持续分析 Agent 的运行参数。

密钥/地址/模型来自本地配置文件 ``config.local.json`` 的 ``llm`` 段
（见 :mod:`stock_selector.utils.app_config`）。本模块只保存行为参数
（节奏、时段、循环上限等），由 ``config.local.json`` 的 ``agent`` 段覆盖。
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple

# 盘中交易时段（含边界）
TRADING_SESSIONS: Tuple[Tuple[str, str], ...] = (
    ('09:30', '11:30'),
    ('13:00', '15:00'),
)

DEFAULT_AGENT_CONFIG: Dict[str, Any] = {
    'enabled': False,
    'interval_sec': 300,          # 盘中每 5 分钟分析一次
    'sessions': [list(x) for x in TRADING_SESSIONS],
    # 每日学习时段：在窗口内每天只跑一次
    'learn_slots': {
        'preopen': {'after': '08:00', 'before': '09:15'},
        'midday': {'after': '11:30', 'before': '12:50'},
        'close': {'after': '15:35', 'before': '17:30'},
    },
    'max_react_rounds': 3,        # 每轮分析最多与模型交互的次数
    'max_tool_calls': 16,         # 单次分析工具调用上限
    'candidates_limit': 20,       # 提供给 agent 的候选数量
    'temperature': 0.25,
    'max_tokens': 2000,
    'timeout_sec': 90,
    'json_mode': False,           # 部分接口支持 response_format=json_object
    'model_trade': '',            # 空则用账户 model
    'model_learn': '',            # 空则用账户 model
}


def default_config() -> Dict[str, Any]:
    """返回深拷贝的默认配置。"""
    import copy

    return copy.deepcopy(DEFAULT_AGENT_CONFIG)


def merge_config(base: Optional[Dict[str, Any]] = None,
                 overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = default_config()
    if base:
        for key, value in base.items():
            if key == 'learn_slots' and isinstance(value, dict):
                cfg['learn_slots'].update(value)
            elif value is not None:
                cfg[key] = value
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                cfg[key] = value
    return cfg


# ---------------------------------------------------------------
# 交易时段 / 学习时段判定
# ---------------------------------------------------------------

def _parse_hhmm(text: str) -> Optional[dtime]:
    try:
        hour, minute = str(text).split(':')
        return dtime(int(hour), int(minute))
    except (ValueError, AttributeError, TypeError):
        return None


def in_trading_session(now: Optional[datetime] = None,
                       sessions: Optional[List] = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    cur = now.time()
    for start, end in (sessions or TRADING_SESSIONS):
        t0, t1 = _parse_hhmm(start), _parse_hhmm(end)
        if t0 and t1 and t0 <= cur <= t1:
            return True
    return False


def current_learn_slot(now: Optional[datetime] = None,
                       learn_slots: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """当前是否落在某个学习时段窗口内；是则返回该时段名。"""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return None
    cur = now.time()
    slots = learn_slots if learn_slots is not None else DEFAULT_AGENT_CONFIG['learn_slots']
    for name, window in (slots or {}).items():
        if not isinstance(window, dict):
            continue
        t0 = _parse_hhmm(window.get('after'))
        t1 = _parse_hhmm(window.get('before'))
        if t0 and t1 and t0 <= cur <= t1:
            return name
    return None


def trade_date_str(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime('%Y-%m-%d')


def today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now()).date()
