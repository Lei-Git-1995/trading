# -*- coding: utf-8 -*-
"""同花顺模拟盘执行通道。

同花顺没有公开的交易 API，这里提供两种模式：
1. manual: 只生成待确认委托，用户在同花顺客户端手动下单。
2. easytrader: 通过 easytrader 自动化同花顺 PC 客户端（可选依赖）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class ManualExecutor:
    """生成待确认委托，不直接操作客户端。"""

    name = 'manual'

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.settings = settings or {}

    def buy(self, code: str, price: float, volume: int) -> Dict[str, Any]:
        return {'ok': True, 'mode': self.name, 'status': 'pending',
                'message': '已生成待确认买入委托'}

    def sell(self, code: str, price: float, volume: int) -> Dict[str, Any]:
        return {'ok': True, 'mode': self.name, 'status': 'pending',
                'message': '已生成待确认卖出委托'}

    def balance(self):
        raise RuntimeError('手动确认模式不读取账户余额，请使用 easytrader 连接客户端')

    def position(self):
        raise RuntimeError('手动确认模式不读取持仓，请使用 easytrader 连接客户端')


class EasytraderExecutor:
    """通过 easytrader 控制同花顺 PC 客户端。"""

    name = 'easytrader'

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.settings = settings or {}
        self.exe_path = self.settings.get('exe_path') or ''
        self._trader = None

    def _client(self):
        if self._trader is None:
            try:
                import easytrader  # noqa: WPS433
            except ImportError as exc:
                raise RuntimeError(
                    '未安装 easytrader，请执行: pip install easytrader') from exc
            trader = easytrader.use('ths')
            if self.exe_path:
                trader.connect(self.exe_path)
            self._trader = trader
        return self._trader

    def buy(self, code: str, price: float, volume: int) -> Dict[str, Any]:
        result = self._client().buy(code, price=price, amount=volume)
        return {'ok': True, 'mode': self.name, 'status': 'submitted', 'raw': result}

    def sell(self, code: str, price: float, volume: int) -> Dict[str, Any]:
        result = self._client().sell(code, price=price, amount=volume)
        return {'ok': True, 'mode': self.name, 'status': 'submitted', 'raw': result}

    def balance(self):
        return self._client().balance

    def position(self):
        return self._client().position


def make_executor(channel: str, settings: Optional[Dict[str, Any]] = None):
    channel = (channel or 'manual').lower()
    if channel == 'easytrader':
        return EasytraderExecutor(settings)
    return ManualExecutor(settings)

