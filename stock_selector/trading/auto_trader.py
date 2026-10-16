# -*- coding: utf-8 -*-
"""LLM 结果与内置模拟盘之间的自动交易和风控桥接。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class PaperAutoTrader:
    """执行一次自动模拟交易周期。

    规则顺序固定为：更新持仓行情 -> 硬止损/止盈 -> AI 卖出 -> AI 买入。
    硬止损和交易所规则不交给模型决定；模型只提供候选和理由。
    """

    def __init__(self, store, account: Dict[str, Any], settings: Optional[Dict[str, Any]] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.store = store
        self.account = account
        self.account_id = int(account['id'])
        self.settings = settings or {}
        self.log = log or print

    def _setting(self, key: str, default: float) -> float:
        value = _num(self.settings.get(key), default)
        return default if value is None else value

    def _quote_map(self, codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        wanted = [str(c).strip().zfill(6) for c in codes if str(c).strip()]
        if not wanted:
            return {}
        try:
            from stock_selector.agent.tools import fetch_quotes
            rows = fetch_quotes(wanted)
        except Exception as exc:  # noqa: BLE001
            self.log(f'[paper] 行情获取失败：{exc}')
            return {}
        return {str(row.get('code')).zfill(6): row for row in rows
                if _num(row.get('price'), 0) and _num(row.get('price'), 0) > 0}

    def _execute(self, *, code: str, name: str, action: str, price: float, volume: int,
                 reason: str, target_price: Optional[float] = None,
                 stop_loss: Optional[float] = None) -> Dict[str, Any]:
        max_position = self._setting('max_position_pct', 10.0)
        order_id = self.store.execute_paper_order(
            self.account_id, code=code, name=name, action=action, price=price,
            volume=volume, reason=reason, max_position_pct=max_position,
            target_price=target_price, stop_loss=stop_loss,
            enforce_t_plus_one=True)
        return {'order_id': order_id, 'code': code, 'action': action,
                'price': price, 'volume': volume, 'reason': reason}

    def run(self, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        result = result or {}
        positions = self.store.get_paper_positions(self.account_id)
        picks = result.get('picks') or []
        codes = [p.get('code') for p in positions] + [p.get('code') for p in picks]
        quotes = self._quote_map(codes)
        self.store.update_paper_prices(self.account_id, {
            code: _num(row.get('price')) for code, row in quotes.items()})

        executed: List[Dict[str, Any]] = []
        blocked: List[Dict[str, Any]] = []
        stop_pct = abs(self._setting('hard_stop_pct', 7.0))
        take_pct = abs(self._setting('take_profit_pct', 15.0))

        # 硬风控优先于 LLM：达到止损/止盈就尝试清仓。
        for position in positions:
            code = position['code']
            price = _num((quotes.get(code) or {}).get('price'))
            if price is None or not position.get('avg_cost'):
                continue
            avg = float(position['avg_cost'])
            pnl_pct = (price / avg - 1.0) * 100.0
            configured_stop = avg * (1 - stop_pct / 100)
            configured_target = avg * (1 + take_pct / 100)
            model_stop = _num(position.get('stop_loss'))
            model_target = _num(position.get('target_price'))
            # 硬阈值永远生效；模型可以收紧，不能把止损放宽或把止盈无限抬高。
            stop_price = max(configured_stop, model_stop) if model_stop else configured_stop
            target_price = min(configured_target, model_target) if model_target else configured_target
            reason = ''
            if price <= stop_price:
                reason = f'硬止损：现价 {price:.3f} <= 止损价 {stop_price:.3f} ({pnl_pct:+.2f}%)'
            elif price >= target_price:
                reason = f'硬止盈：现价 {price:.3f} >= 目标价 {target_price:.3f} ({pnl_pct:+.2f}%)'
            if not reason:
                continue
            try:
                executed.append(self._execute(code=code, name=position.get('name') or '',
                                              action='sell', price=price,
                                              volume=int(position['volume']), reason=reason))
            except Exception as exc:  # T+1 或其他模拟盘约束
                blocked.append({'code': code, 'action': 'sell', 'reason': f'{reason}；未成交：{exc}'})
                self.log(f'[paper] {code} 风控卖出未成交：{exc}')

        # 只有盘中交易分析才产生新开仓；学习批次只沉淀经验，不交易。
        if result.get('session') == 'learn' or result.get('status') not in ('ok', 'skipped'):
            return {'executed': executed, 'blocked': blocked, 'quotes': len(quotes)}

        confidence_min = self._setting('min_ai_confidence', 60.0)
        lots = max(1, int(self._setting('trade_lots', 1)))
        no_buy_after = str(self.settings.get('no_buy_after') or '14:45')
        now = datetime.now().strftime('%H:%M')
        candidate_codes = {str(c).zfill(6) for c in (result.get('candidate_codes') or [])}
        for pick in picks:
            action = str(pick.get('action') or 'watch').lower()
            if action not in ('buy', 'sell'):
                continue
            code = str(pick.get('code') or '').strip().zfill(6)
            quote = quotes.get(code) or {}
            # 自动交易要求本周期拿到新行情，禁止使用模型猜测或旧选股价格。
            price = _num(quote.get('price'))
            if price is None or price <= 0:
                continue
            confidence = _num(pick.get('confidence'), 100.0)
            if action == 'buy':
                if code not in candidate_codes:
                    blocked.append({'code': code, 'action': action, 'reason': '不在本轮选股候选范围内'})
                    continue
                if now > no_buy_after:
                    blocked.append({'code': code, 'action': action, 'reason': f'超过开仓时间 {no_buy_after}'})
                    continue
                if confidence < confidence_min:
                    blocked.append({'code': code, 'action': action, 'reason': f'置信度 {confidence:.1f} < {confidence_min:.1f}'})
                    continue
                if self.store.has_paper_trade_today(self.account_id, code, 'buy'):
                    continue
                volume = lots * 100
                target = _num(pick.get('target_price'))
                stop = _num(pick.get('stop_loss'))
                if target is None or target <= price:
                    target = price * (1 + take_pct / 100)
                if stop is None or stop >= price:
                    stop = price * (1 - stop_pct / 100)
            else:
                position = next((p for p in self.store.get_paper_positions(self.account_id)
                                 if p['code'] == code), None)
                if not position or self.store.has_paper_trade_today(self.account_id, code, 'sell'):
                    continue
                volume = int(position['volume'])
                target = None
                stop = None
            try:
                executed.append(self._execute(
                    code=code, name=str(pick.get('name') or ''), action=action,
                    price=price, volume=volume,
                    reason=f'AI决策：{pick.get("reason") or "无"}',
                    target_price=target, stop_loss=stop))
            except Exception as exc:
                blocked.append({'code': code, 'action': action, 'reason': str(exc)})
                self.log(f'[paper] AI {action} {code} 未成交：{exc}')
        return {'executed': executed, 'blocked': blocked, 'quotes': len(quotes)}
