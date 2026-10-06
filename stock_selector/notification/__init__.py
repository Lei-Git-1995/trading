"""选股结果通知工具。"""

from .webhook import WebhookNotifier, format_stock_summary

__all__ = ['WebhookNotifier', 'format_stock_summary']
