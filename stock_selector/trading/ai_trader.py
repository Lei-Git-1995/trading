# -*- coding: utf-8 -*-
"""AI 交易决策：把选股结果交给大模型，生成结构化买卖订单。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import requests


DEFAULT_BASE_URL = 'https://api.openai.com/v1'

SYSTEM_PROMPT = (
    '你是一个 A 股短线量化交易助理。根据给定的股票候选数据和当前持仓，'
    '输出结构化交易计划。只输出 JSON，不要输出多余文字。'
    'JSON 格式: {"summary": "简要说明", "orders": [{"action": "buy|sell", '
    '"code": "股票代码", "name": "名称", "price": 数值, "volume": 股数(100整数倍), '
    '"reason": "中文理由"}]}。没有机会时 orders 返回空数组。'
    '买入必须考虑仓位控制，单只不超过总资金的指定比例。'
)


class AIAdvisor:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL,
                 model: str = 'gpt-4o-mini', timeout: int = 60):
        self.api_key = (api_key or '').strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip('/')
        self.model = model or 'gpt-4o-mini'
        self.timeout = int(timeout or 60)

    def chat(self, user_prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError('请先填写 AI API Key')
        resp = requests.post(
            f'{self.base_url}/chat/completions',
            headers={'Authorization': f'Bearer {self.api_key}',
                     'Content-Type': 'application/json'},
            json={'model': self.model,
                  'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                               {'role': 'user', 'content': user_prompt}],
                  'temperature': 0.2},
            timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']

    def analyze(self, rows: List[Dict[str, Any]], *, positions: Optional[Any] = None,
                cash: Optional[float] = None, max_position_pct: float = 10.0) -> Dict[str, Any]:
        lines = []
        for row in rows[:60]:
            parts = [f"代码{row.get('代码') or row.get('code', '')}",
                     f"名称{row.get('名称') or row.get('name', '')}",
                     f"行业{row.get('行业/板块') or row.get('sector', '')}",
                     f"价格{row.get('价格') or row.get('price', '')}",
                     f"涨跌{row.get('涨跌幅%') or row.get('change_pct', '')}",
                     f"换手{row.get('换手%') or row.get('turnover', '')}",
                     f"量比{row.get('量比') or row.get('volume_ratio', '')}",
                     f"评分{row.get('评分') or row.get('score', '')}",
                     f"说明{row.get('说明') or row.get('reason', '')}"]
            lines.append(' '.join(str(p) for p in parts))
        user = '候选股票:\n' + '\n'.join(lines)
        user += f'\n\n总资金约: {cash if cash is not None else "未知"}'
        user += f'\n单只最大仓位: {max_position_pct}%'
        user += '\n当前持仓:\n' + (str(positions) if positions else '无')
        return self._parse(self.chat(user))

    @staticmethod
    def _parse(text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        match = re.search(r'\{.*\}', text, re.S)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f'AI 返回内容无法解析为 JSON: {text[:200]}')

    @staticmethod
    def normalize_orders(decision: Dict[str, Any]) -> List[Dict[str, Any]]:
        orders = []
        for item in decision.get('orders') or []:
            try:
                action = str(item.get('action', '')).lower()
                code = str(item.get('code', '')).strip()
                price = float(item.get('price') or 0)
                volume = int(item.get('volume') or 0)
            except (TypeError, ValueError):
                continue
            if action not in ('buy', 'sell') or not code or price <= 0:
                continue
            volume = max(0, volume // 100 * 100)
            if volume <= 0:
                continue
            orders.append({'action': action, 'code': code,
                           'name': str(item.get('name') or ''),
                           'price': price, 'volume': volume,
                           'reason': str(item.get('reason') or '')})
        return orders
