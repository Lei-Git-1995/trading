"""持仓风控价校验与模拟盘止盈止损检查。"""
from datetime import datetime, timedelta, timezone
import math


def risk_prices(target_price=None, stop_loss=None, buy_price=None):
    def parse(value):
        if value is None or str(value).strip() == '':
            return None
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError('止盈价和止损价必须是大于0的有限数字')
        return value
    target, stop = parse(target_price), parse(stop_loss)
    if target is not None and stop is not None and stop >= target:
        raise ValueError('止损价必须低于止盈价')
    if buy_price is not None:
        if target is not None and target <= buy_price:
            raise ValueError('止盈价必须高于买入价')
        if stop is not None and stop >= buy_price:
            raise ValueError('止损价必须低于买入价')
    return target, stop


def check_position_risk(store, account_id, fetch_quotes, now=None, enabled=lambda: True):
    """只按本次新鲜行情检查显式设置的价位，不提交 AI 买入。"""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    clock = now.strftime('%H:%M')
    if now.weekday() >= 5 or not ('09:30' <= clock <= '11:30' or '13:00' <= clock < '15:00'):
        return {'executed': [], 'blocked': [], 'status': '等待盘中行情'}
    positions = store.get_paper_positions(account_id)
    if not positions:
        return {'executed': [], 'blocked': [], 'status': '暂无持仓'}
    if not enabled():
        return {'executed': [], 'blocked': [], 'status': '自动止盈止损已暂停'}
    quotes = {}
    for row in fetch_quotes([p['code'] for p in positions]):
        try:
            price = float(row['price'])
            raw_stamp = str(row['quote_time']).strip()
            stamp = None
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y%m%d%H%M%S'):
                try:
                    stamp = datetime.strptime(raw_stamp, fmt).replace(tzinfo=now.tzinfo)
                    break
                except ValueError:
                    continue
            if stamp is None:
                continue
            age = (now - stamp).total_seconds()
            if math.isfinite(price) and price > 0 and 0 <= age <= 120:
                quotes[str(row['code']).zfill(6)] = price
        except (KeyError, TypeError, ValueError):
            continue
    store.update_paper_prices(account_id, quotes)
    executed, blocked = [], []
    for p in positions:
        price = quotes.get(p['code'])
        if price is None:
            continue
        target, stop = risk_prices(p.get('target_price'), p.get('stop_loss'))
        reason = '止损' if stop is not None and price <= stop else (
            '止盈' if target is not None and price >= target else '')
        if not reason or not enabled():
            continue
        try:
            order_id = store.execute_paper_order(
                account_id, code=p['code'], name=p['name'], action='sell',
                price=price, volume=int(p['volume']), reason=f'持仓自动{reason}（触发行情 {price:.3f}）',
                enforce_t_plus_one=True)
            executed.append(f"{p['code']} {reason}成交 #{order_id}")
        except Exception as exc:
            blocked.append(f"{p['code']} {reason}未成交：{exc}")
    return {'executed': executed, 'blocked': blocked,
            'status': f'有效行情 {len(quotes)}/{len(positions)} 只'}
