# -*- coding: utf-8 -*-
"""Agent 可调用的工具集。

工具分三类：
    - observe：取证（行情、板块、资金流、候选、自选、记忆、战法）
    - action：写操作（更新记忆、战法库、自选分组）
    - decide：产出结论（submit_analysis / skip），调用后本轮分析结束

每个工具返回 JSON 可序列化 dict；出错时返回 ``{"ok": false, "error": ...}``，
绝不抛异常，保证 Agent 循环稳定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests


# ---------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------

@dataclass
class ToolContext:
    store: Any = None                 # PostgresStore
    agent_store: Any = None           # AgentStore
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    log: Callable[[str], None] = print
    _provider: Any = None
    _provider_mgr: Any = None

    def get_provider(self):
        if self._provider is not None:
            return self._provider
        try:
            from stock_selector.data.smart_provider_manager import SmartProviderManager
            self._provider_mgr = SmartProviderManager()
            self._provider = self._provider_mgr.get_provider()
        except Exception as exc:  # noqa: BLE001
            self.log(f'数据源初始化失败: {exc}')
            self._provider = None
        return self._provider


# ---------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------

OBSERVE = 'observe'
ACTION = 'action'
DECIDE = 'decide'

TOOL_SPECS: List[Dict[str, str]] = [
    {'name': 'get_market_overview', 'category': OBSERVE,
     'desc': '获取大盘指数与行业板块涨跌/资金榜（无需参数）', 'args': '{}'},
    {'name': 'get_quotes', 'category': OBSERVE,
     'desc': '批量获取个股实时行情', 'args': '{"codes": ["600000", "000001"]}'},
    {'name': 'get_history', 'category': OBSERVE,
     'desc': '获取个股近 N 日 K 线（收盘/涨跌幅/成交量/换手率）',
     'args': '{"code": "600000", "days": 20}'},
    {'name': 'get_capital_flow', 'category': OBSERVE,
     'desc': '获取个股主力资金流（实时净流入、大单占比）', 'args': '{"code": "600000"}'},
    {'name': 'get_sector_ranking', 'category': OBSERVE,
     'desc': '获取行业板块涨跌幅排行', 'args': '{"limit": 10}'},
    {'name': 'list_candidates', 'category': OBSERVE,
     'desc': '列出本次待研判的候选股票（来自当日选股结果）', 'args': '{}'},
    {'name': 'list_watchlist', 'category': OBSERVE,
     'desc': '列出自选股分组与成分股', 'args': '{}'},
    {'name': 'read_memory', 'category': OBSERVE,
     'desc': '读取历史记忆（此前沉淀的判断与教训）', 'args': '{}'},
    {'name': 'read_trade_history', 'category': OBSERVE,
     'desc': '读取模拟盘最近成交和盈亏，用于复盘学习', 'args': '{"limit": 20}'},
    {'name': 'read_playbook', 'category': OBSERVE,
     'desc': '读取战法库（选股/择时经验）', 'args': '{}'},
    {'name': 'save_memory', 'category': ACTION,
     'desc': '写入/更新一条长期记忆',
     'args': '{"key": "market_phase", "value": "退潮期，控制仓位"}'},
    {'name': 'update_playbook', 'category': ACTION,
     'desc': '向战法库沉淀一条经验',
     'args': '{"section": "选股", "content": "...", "note": "来源"}'},
    {'name': 'add_to_watchlist', 'category': ACTION,
     'desc': '把股票加入自选分组（分组不存在会创建）',
     'args': '{"code": "600000", "name": "浦发银行", "group": "AI关注"}'},
    {'name': 'submit_analysis', 'category': DECIDE,
     'desc': '提交最终研判（调用后本轮结束）',
     'args': '{"summary": "一句话", "market_view": "大盘研判", "confidence": 60, '
             '"picks": [{"code": "600000", "name": "", "action": "buy|sell|watch|avoid", '
             '"rank": 1, "confidence": 70, "price": 10.0, "target_price": 11.0, '
             '"stop_loss": 9.5, "reason": "理由"}], "lessons": "学习时段沉淀"}',
     },
    {'name': 'skip', 'category': DECIDE,
     'desc': '本轮不给出研判（无机会或数据不足）', 'args': '{"reason": "..."}'},
]

TOOL_MAP: Dict[str, Dict[str, str]] = {spec['name']: spec for spec in TOOL_SPECS}
OBSERVE_TOOLS = [s['name'] for s in TOOL_SPECS if s['category'] == OBSERVE]
ACTION_TOOLS = [s['name'] for s in TOOL_SPECS if s['category'] == ACTION]
DECIDE_TOOLS = [s['name'] for s in TOOL_SPECS if s['category'] == DECIDE]
TOOL_NAMES = OBSERVE_TOOLS + ACTION_TOOLS + DECIDE_TOOLS


# ---------------------------------------------------------------
# 行情抓取（腾讯，快速、免东财）
# ---------------------------------------------------------------

def _to_symbol(code6: str) -> str:
    code6 = str(code6).strip().zfill(6)
    if code6.startswith('6') or code6.startswith('9'):
        return f'sh{code6}'
    if code6.startswith(('4', '8')):
        return f'bj{code6}'
    return f'sz{code6}'


def fetch_quotes(codes: List[str], timeout: int = 6) -> List[Dict[str, Any]]:
    """用腾讯 qt.gtimg.cn 批量取个股行情。"""
    wanted = [str(c).strip().zfill(6) for c in codes if str(c).strip()]
    if not wanted:
        return []
    symbols = ','.join(_to_symbol(c) for c in wanted)
    url = 'https://qt.gtimg.cn/q=' + symbols
    try:
        resp = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'})
        resp.encoding = 'gb18030'
        text = resp.text
    except Exception:  # noqa: BLE001
        return []
    rows: List[Dict[str, Any]] = []
    for line in text.strip().split('\n'):
        if '=' not in line:
            continue
        left, right = line.split('=', 1)
        code6 = left.strip().replace('v_', '')[-6:]
        fields = right.strip().strip(';').strip('"').split('~')
        if len(fields) < 33:
            continue

        def _f(idx):
            try:
                return float(fields[idx])
            except (ValueError, IndexError):
                return None

        rows.append({
            'code': code6,
            'name': fields[1],
            'price': _f(3),
            'prev_close': _f(4),
            'open': _f(5),
            'high': _f(33),
            'low': _f(34),
            'change': _f(31),
            'pct_chg': _f(32),
            'volume': _f(36),
            'amount_wan': _f(37),
            'turnover': _f(38),
        })
    return rows


# ---------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------

def _tool_market_overview(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from stock_selector.data.market_board import fetch_market_snapshot
    snap = fetch_market_snapshot(board_limit=int(args.get('board_limit') or 8))
    return {'ok': True, 'indices': snap.get('indices', []),
            'gainers': snap.get('gainers', []), 'losers': snap.get('losers', []),
            'sort_key': snap.get('sort_key'), 'time': snap.get('time'),
            'board_source': snap.get('board_source')}


def _tool_quotes(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    codes = args.get('codes') or []
    if isinstance(codes, str):
        codes = [c for c in codes.replace('，', ',').split(',') if c.strip()]
    rows = fetch_quotes(codes)
    return {'ok': True, 'quotes': rows, 'count': len(rows)}


def _tool_history(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    code = str(args.get('code') or '').strip().zfill(6)
    days = int(args.get('days') or 20)
    if not code.isdigit():
        return {'ok': False, 'error': 'code 无效'}
    provider = ctx.get_provider()
    if provider is None:
        return {'ok': False, 'error': '无可用数据源'}
    try:
        df = provider.get_stock_history(code, days)
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': f'K线获取失败: {exc}'}
    if df is None or getattr(df, 'empty', True):
        return {'ok': False, 'error': '无 K 线数据'}
    records = []
    for _, row in df.tail(days).iterrows():
        records.append({
            'date': str(row.get('日期', '')),
            'open': _num(row.get('开盘')), 'close': _num(row.get('收盘')),
            'high': _num(row.get('最高')), 'low': _num(row.get('最低')),
            'volume': _num(row.get('成交量')), 'amount': _num(row.get('成交额')),
            'pct_chg': _num(row.get('涨跌幅')), 'turnover': _num(row.get('换手率')),
        })
    return {'ok': True, 'code': code, 'days': len(records), 'kline': records}


def _tool_capital_flow(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    code = str(args.get('code') or '').strip().zfill(6)
    if not code.isdigit():
        return {'ok': False, 'error': 'code 无效'}
    from stock_selector.data.capital_flow_client import CapitalFlowClient
    client = CapitalFlowClient()
    realtime = client.get_realtime_flow(code)
    return {'ok': True, 'code': code, 'realtime': realtime}


def _tool_sector_ranking(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get('limit') or 10)
    # 优先东方财富细分行业，失败时回退腾讯综合行业榜（与右侧面板同源）
    from stock_selector.data.market_board import MarketBoardClient
    client = MarketBoardClient()
    boards = []
    try:
        from stock_selector.data.sector_client import SectorClient
        df = SectorClient().get_all_sectors()
        if df is not None and not getattr(df, 'empty', True):
            df = df.sort_values('涨跌幅', ascending=False)
            boards = [{'name': r.get('板块名称'), 'pct_chg': r.get('涨跌幅'),
                       'leader': r.get('领涨股')} for r in df.to_dict('records')]
            source = '东方财富细分行业'
    except Exception:  # noqa: BLE001
        boards = []
        source = ''
    if not boards:
        try:
            raw = client.fetch_industry_boards(pz=max(50, limit))
            boards = [{'name': b.get('name'), 'pct_chg': b.get('pct_chg'),
                       'pct_chg_5d': b.get('pct_chg_5d'), 'main_net_yi': b.get('main_net_yi'),
                       'leader': b.get('leader')} for b in raw]
            source = client.last_board_source
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'error': f'板块数据不可用: {exc}'}
    if not boards:
        return {'ok': False, 'error': '板块数据不可用'}
    boards.sort(key=lambda b: b.get('pct_chg') or 0, reverse=True)
    return {'ok': True, 'source': source,
            'top': boards[:limit], 'bottom': boards[-limit:][::-1]}


def _tool_candidates(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get('limit') or 0) or len(ctx.candidates)
    return {'ok': True, 'count': len(ctx.candidates),
            'candidates': ctx.candidates[:limit]}


def _tool_watchlist(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.store is None:
        return {'ok': False, 'error': '未配置数据库'}
    try:
        groups = ctx.store.list_groups()
        result = []
        for g in groups:
            try:
                stocks = ctx.store.list_stocks(g['name'])
            except Exception:  # noqa: BLE001
                stocks = []
            result.append({'group': g['name'], 'stocks': stocks})
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc)}
    return {'ok': True, 'groups': result}


def _tool_read_memory(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.agent_store is None:
        return {'ok': False, 'error': '未配置数据库'}
    try:
        return {'ok': True, 'memory': ctx.agent_store.get_memory()}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc)}


def _tool_trade_history(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.store is None or not ctx.account:
        return {'ok': False, 'error': '未配置模拟盘账户'}
    try:
        rows = ctx.store.list_paper_trades(ctx.account['id'], int(args.get('limit') or 20))
        return {'ok': True, 'trades': rows, 'count': len(rows)}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc)}


def _tool_read_playbook(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.agent_store is None:
        return {'ok': False, 'error': '未配置数据库'}
    try:
        return {'ok': True, 'playbook': ctx.agent_store.get_playbook()}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc)}


def _tool_save_memory(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    key = str(args.get('key') or '').strip()
    if not key:
        return {'ok': False, 'error': 'key 不能为空'}
    if ctx.agent_store is None:
        return {'ok': False, 'error': '未配置数据库'}
    try:
        ctx.agent_store.set_memory(key, args.get('value'))
        return {'ok': True, 'key': key}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc)}


def _tool_update_playbook(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.agent_store is None:
        return {'ok': False, 'error': '未配置数据库'}
    try:
        ctx.agent_store.add_playbook(str(args.get('section') or 'general'),
                                     args.get('content'), str(args.get('note') or ''))
        return {'ok': True}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc)}


def _tool_add_watchlist(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    code = str(args.get('code') or '').strip().zfill(6)
    group = str(args.get('group') or 'AI关注').strip() or 'AI关注'
    if not code.isdigit():
        return {'ok': False, 'error': 'code 无效'}
    if ctx.store is None:
        return {'ok': False, 'error': '未配置数据库'}
    try:
        ctx.store.create_group(group)
        ctx.store.add_stock(group, code, str(args.get('name') or ''))
        return {'ok': True, 'code': code, 'group': group}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc)}


# decide 工具由 loop 处理，这里仅占位保证白名单一致
def _tool_noop(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    return {'ok': True}


def _num(value):
    try:
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


HANDLERS: Dict[str, Callable[[ToolContext, Dict[str, Any]], Dict[str, Any]]] = {
    'get_market_overview': _tool_market_overview,
    'get_quotes': _tool_quotes,
    'get_history': _tool_history,
    'get_capital_flow': _tool_capital_flow,
    'get_sector_ranking': _tool_sector_ranking,
    'list_candidates': _tool_candidates,
    'list_watchlist': _tool_watchlist,
    'read_memory': _tool_read_memory,
    'read_trade_history': _tool_trade_history,
    'read_playbook': _tool_read_playbook,
    'save_memory': _tool_save_memory,
    'update_playbook': _tool_update_playbook,
    'add_to_watchlist': _tool_add_watchlist,
}


def run_tool(name: str, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """执行一个 observe/action 工具。decide 工具不由本函数处理。"""
    if name not in HANDLERS:
        return {'ok': False, 'error': f'未实现的工具: {name}'}
    try:
        return HANDLERS[name](ctx, args or {})
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': f'工具执行异常: {exc}'}


def tool_prompt_lines() -> List[str]:
    """给系统提示用的工具清单。"""
    lines = ['可用工具（tool 名称 + 参数示例）：']
    for category, label in ((OBSERVE, '【取证】'), (ACTION, '【写操作】'), (DECIDE, '【产出】')):
        for spec in TOOL_SPECS:
            if spec['category'] == category:
                lines.append(f"- {spec['name']} {spec['args']}  // {spec['desc']}")
    return lines
