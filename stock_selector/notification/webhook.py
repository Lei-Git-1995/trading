"""通用 Webhook 通知。

兼容钉钉、企业微信等支持 JSON POST 的机器人；不配置 URL 时不会发送网络请求。
"""
from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional
from urllib.request import Request, urlopen


def format_stock_summary(stocks: Iterable[Mapping], title: str = '选股结果') -> str:
    rows = list(stocks)
    lines = [f'{title}：{len(rows)} 只']
    for stock in rows[:10]:
        code = stock.get('code', '')
        name = stock.get('name', '')
        change = stock.get('change_pct', '')
        score = stock.get('score', '')
        lines.append(f'- {code} {name} 涨跌幅:{change}% 评分:{score}')
    if len(rows) > 10:
        lines.append(f'其余 {len(rows) - 10} 只请查看报告。')
    return '\n'.join(lines)


class WebhookNotifier:
    """发送简单文本消息到通用机器人 Webhook。"""

    def __init__(self, url: Optional[str], timeout: int = 10):
        self.url = url
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def send_text(self, text: str) -> bool:
        if not self.url:
            return False
        payload = json.dumps({'msgtype': 'text', 'text': {'content': text}}, ensure_ascii=False).encode('utf-8')
        request = Request(self.url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=self.timeout) as response:
            return 200 <= response.status < 300
