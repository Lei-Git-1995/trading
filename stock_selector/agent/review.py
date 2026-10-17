# -*- coding: utf-8 -*-
"""研判结果跟踪与多轮复盘。

把历史 ``agent_picks`` 中带价格的 buy 研判，与后续真实行情对照，
计算涨跌幅与是否命中（盈利），写入 ``agent_pick_reviews``，
从而让模型在多轮分析中「记得自己此前的判断准不准」。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Dict, List, Optional


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def evaluate_pick_outcomes(store, agent_store, fetch_quotes,
                           lookback_days: int = 15,
                           log: Optional[Callable[[str], None]] = None,
                           today: Optional[date] = None) -> Dict[str, Any]:
    """评估近期未复盘的 buy 研判，落库为 ``agent_pick_reviews``。"""
    log = log or (lambda *_a, **_k: None)
    if store is None or agent_store is None:
        return {'evaluated': 0, 'skipped': 0, 'reason': '缺少数据存储'}
    try:
        pending = agent_store.unreviewed_picks(lookback_days=lookback_days)
    except Exception as exc:  # noqa: BLE001
        log(f'[review] 读取待复盘研判失败: {exc}')
        return {'evaluated': 0, 'skipped': 0, 'reason': str(exc)}
    if not pending:
        return {'evaluated': 0, 'skipped': 0, 'reason': '无待复盘研判'}

    codes = sorted({str(p['code']).zfill(6) for p in pending if p.get('code')})
    quotes: Dict[str, Dict[str, Any]] = {}
    try:
        for row in fetch_quotes(codes):
            quotes[str(row.get('code')).zfill(6)] = row
    except Exception as exc:  # noqa: BLE001
        log(f'[review] 行情获取失败: {exc}')
        return {'evaluated': 0, 'skipped': len(pending), 'reason': str(exc)}

    now = today or date.today()
    evaluated = skipped = 0
    for pick in pending:
        code = str(pick['code']).zfill(6)
        quote = quotes.get(code) or {}
        eval_price = _num(quote.get('price'))
        pick_price = _num(pick.get('price'))
        if eval_price is None or eval_price <= 0 or pick_price is None or pick_price <= 0:
            skipped += 1
            continue
        ret_pct = (eval_price / pick_price - 1.0) * 100.0
        try:
            agent_store.add_pick_review(
                analysis_id=pick.get('analysis_id'), code=code,
                name=pick.get('name') or '', action=pick.get('action') or 'buy',
                pick_date=pick.get('pick_date'), pick_price=pick_price,
                eval_date=now, eval_price=eval_price,
                ret_pct=round(ret_pct, 2), hit=ret_pct > 0,
                note='自动跟踪')
            evaluated += 1
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            log(f'[review] {code} 复盘落库失败: {exc}')
    log(f'[review] 复盘完成：评估 {evaluated} 只，跳过 {skipped} 只')
    return {'evaluated': evaluated, 'skipped': skipped}
