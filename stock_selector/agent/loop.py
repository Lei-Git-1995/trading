# -*- coding: utf-8 -*-
"""ReAct 工具循环。

与「致富研究员」一致，采用纯文本 JSON 工具协议：
    模型每轮输出 ``{"goal": "...", "steps": [{"tool": "...", "args": {...}}, ...]}``，
宿主执行 observe/action 工具并把结果回灌，直到模型调用 decide 工具
（submit_analysis / skip）或达到轮次上限。
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from stock_selector.agent import tools as agent_tools
from stock_selector.agent.llm import LLMClient, extract_json


def _clip(text: Any, limit: int = 400) -> str:
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + '…'


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ''):
            return None
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _digest(playbook: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for section, content in list(playbook.items())[:8]:
        out[str(section)] = _clip(content, 300)
    return out


def _memory_digest(memory: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, item in list(memory.items())[:12]:
        value = item.get('value') if isinstance(item, dict) and 'value' in item else item
        out[str(key)] = _clip(value, 300)
    return out


def _system_prompt() -> str:
    lines = [
        '你是「A股短线研判 Agent」，拥有取证工具，负责给出「大盘研判 + 个股排序」。',
        '你只做分析与建议，不直接下单；所有结论供人工参考。',
        '',
        '【工作方式】',
        '1) 先调用取证工具了解大盘、板块、候选、资金与持仓，再下结论；',
        '2) 涉及持仓决策时，必须先 get_positions 读取持仓，并用 read_trade_history /',
        '   review_performance 复盘近期成交与研判胜率，再决定卖出或加仓；',
        '3) 每轮可调用多个工具，但请节约调用、避免重复查询；',
        '4) 必须且只能通过 submit_analysis 或 skip 结束本轮。',
        '',
        '【交易纪律（A股）】',
        '- T+1：当日买入不能当日卖出；涨跌停价附近无法成交；ST/退市风险股回避；',
        '- 结论必须基于工具返回的真实数据，不得编造行情、价格或新闻；',
        '- 控制仓位、分散持股；单票不重仓，亏损股不加仓摊薄；',
        '- 给买入建议时必须同时给出 target_price（止盈）与 stop_loss（止损），',
        '  且满足 stop_loss < price < target_price；缺失或不合理一律按风险否决。',
        '',
        '【产出要求】',
        '- 候选 1~8 只，按 rank 排序，action∈{buy,sell,watch,avoid}；',
        '- confidence 取 0~100 的整数，越低越谨慎；',
        '- 每只都给出简洁 reason（引用数据），避免空话。',
        '- 学习批次（session=learn）：重点输出 lessons，并调用 update_playbook /',
        '  save_memory 沉淀可复用的经验与教训，不下单。',
        '',
    ]
    lines.extend(agent_tools.tool_prompt_lines())
    lines.append('')
    lines.append('每轮只输出 JSON：{"goal":"简述目标","steps":[{"tool":"名称","args":{...}}]}')
    lines.append('当信息足够时，steps 中直接包含 {"tool":"submit_analysis","args":{...}}。')
    return '\n'.join(lines)


class ReActAgent:
    def __init__(self, llm: LLMClient, ctx: agent_tools.ToolContext,
                 agent_cfg: Optional[Dict[str, Any]] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.llm = llm
        self.ctx = ctx
        self.cfg = agent_cfg or {}
        self.log = log or ctx.log
        self.max_rounds = int(self.cfg.get('max_react_rounds') or 3)
        self.max_tool_calls = int(self.cfg.get('max_tool_calls') or 16)

    # ---------------- 构建输入 ----------------

    def _user_payload(self, session: str, trigger: str) -> Dict[str, Any]:
        ctx = self.ctx
        candidates = []
        for row in (ctx.candidates or [])[:int(self.cfg.get('candidates_limit') or 20)]:
            candidates.append({
                'code': row.get('code'), 'name': row.get('name'),
                'price': row.get('price'), 'change_pct': row.get('change_pct'),
                'turnover': row.get('turnover'), 'volume_ratio': row.get('volume_ratio'),
                'amount': row.get('amount'), 'score': row.get('score'),
                'sector': row.get('sector'), 'explanation': row.get('explanation'),
            })
        now = time.localtime()
        payload: Dict[str, Any] = {
            'session': session,
            'trigger': trigger,
            'date': time.strftime('%Y-%m-%d', now),
            'weekday': '一二三四五六日'[now.tm_wday],
            'time': time.strftime('%H:%M:%S', now),
            'candidate_count': len(ctx.candidates or []),
            'candidates': candidates,
            'max_react_rounds': self.max_rounds,
        }
        if session == 'learn':
            payload['task'] = '学习批次：复盘近期研判与成交，沉淀教训与战法，不产生买入。'
        else:
            payload['task'] = '盘中研判：结合持仓给出卖出/加仓与新的买入候选。'

        # 记忆 / 战法 / 绩效 / 持仓：直接内联，减少一次来回
        try:
            if ctx.agent_store:
                payload['performance'] = ctx.agent_store.performance_summary(days=30)
                playbook = ctx.agent_store.get_playbook()
                payload['playbook_sections'] = list(playbook.keys())
                payload['playbook_digest'] = _digest(playbook)
                memory = ctx.agent_store.get_memory()
                payload['memory_keys'] = list(memory.keys())
                payload['memory_digest'] = _memory_digest(memory)
        except Exception:  # noqa: BLE001
            pass
        try:
            if ctx.store is not None and ctx.account:
                positions = ctx.store.get_paper_positions(ctx.account['id'])
                payload['account'] = {
                    'cash_balance': ctx.account.get('cash_balance'),
                    'initial_cash': ctx.account.get('initial_cash'),
                    'position_count': len(positions),
                }
                payload['positions'] = [{
                    'code': p.get('code'), 'name': p.get('name'),
                    'volume': p.get('volume'), 'avg_cost': p.get('avg_cost'),
                    'last_price': p.get('last_price'), 'target_price': p.get('target_price'),
                    'stop_loss': p.get('stop_loss'), 'opened_on': str(p.get('opened_on') or ''),
                } for p in positions]
        except Exception:  # noqa: BLE001
            pass
        payload['note'] = ('完整记忆/战法可调用 read_memory / read_playbook；'
                           '实时持仓盈亏可调用 get_positions；'
                           '历史研判胜率可调用 review_performance。')
        return payload

    # ---------------- 主循环 ----------------

    def run(self, *, session: str = 'intraday', trigger: str = 'interval',
            kind: str = 'trade') -> Dict[str, Any]:
        started = time.time()
        result: Dict[str, Any] = {
            'status': 'error', 'summary': '', 'market_view': '', 'confidence': None,
            'picks': [], 'lessons': '', 'goal': '', 'trace': [], 'rounds': 0,
            'tool_calls': 0, 'raw': {}, 'usage': {}, 'error': '',
            'model': self.llm.model_learn if kind == 'learn' else self.llm.model_trade,
        }
        if not self.llm.available:
            result['error'] = '未配置 API Key（请在「配置」页填写并保存）'
            return result

        messages: List[Dict[str, Any]] = [
            {'role': 'system', 'content': _system_prompt()},
            {'role': 'user', 'content': json.dumps(self._user_payload(session, trigger),
                                                    ensure_ascii=False)},
        ]
        trace: List[Dict[str, Any]] = []
        decide: Optional[Dict[str, Any]] = None
        raw_last: Dict[str, Any] = {}

        for round_no in range(1, self.max_rounds + 1):
            result['rounds'] = round_no
            resp = self.llm.chat(messages, kind=kind)
            result['usage'] = self.llm.last_usage
            if not resp.get('ok'):
                result['error'] = resp.get('error') or '模型调用失败'
                self.log(f'[agent] 第{round_no}轮模型调用失败: {result["error"]}')
                break
            text = resp.get('text') or ''
            raw_last = resp.get('raw') or {}
            messages.append({'role': 'assistant', 'content': text})

            obj = extract_json(text)
            steps = obj.get('steps') if isinstance(obj, dict) else None
            if isinstance(obj, dict) and obj.get('goal'):
                result['goal'] = str(obj.get('goal'))[:200]
            if not isinstance(steps, list) or not steps:
                # 让模型改用工具协议重试
                messages.append({'role': 'user', 'content': json.dumps({
                    'error': '未解析到 steps，请严格输出 {"goal":...,"steps":[{"tool":...,"args":{...}}]}',
                }, ensure_ascii=False)})
                continue

            round_results = []
            for step in steps:
                if not isinstance(step, dict):
                    continue
                tool = str(step.get('tool') or '').strip()
                args = step.get('args') if isinstance(step.get('args'), dict) else {}
                if tool in agent_tools.DECIDE_TOOLS:
                    decide = {'tool': tool, 'args': args, 'round': round_no}
                    break
                if tool not in agent_tools.TOOL_NAMES:
                    round_results.append({'tool': tool, 'result': {'ok': False, 'error': '未知工具'}})
                    continue
                if result['tool_calls'] >= self.max_tool_calls:
                    round_results.append({'tool': tool, 'result': {'ok': False, 'error': '工具调用已达上限'}})
                    continue
                t0 = time.time()
                out = agent_tools.run_tool(tool, args, self.ctx)
                elapsed = int((time.time() - t0) * 1000)
                result['tool_calls'] += 1
                trace.append({'round': round_no, 'tool': tool, 'args': args,
                              'result': out, 'ok': bool(out.get('ok')),
                              'error': out.get('error') or '', 'elapsed_ms': elapsed})
                self.log(f'[agent] 工具 {tool} → {"ok" if out.get("ok") else out.get("error")}')
                round_results.append({'tool': tool, 'result': out})
            if decide is not None:
                break
            messages.append({'role': 'user', 'content': json.dumps({
                'tool_results': round_results,
                'notice': '继续调用工具，或直接 submit_analysis / skip 结束。',
            }, ensure_ascii=False)})

        # ---------------- 收尾 ----------------
        result['trace'] = trace
        if decide is not None:
            if decide['tool'] == 'skip':
                result['status'] = 'skipped'
                result['summary'] = str(decide['args'].get('reason') or '本轮跳过')
            else:
                self._apply_analysis(decide['args'], result)
        elif result['error']:
            result['status'] = 'error'
        else:
            result['status'] = 'error'
            result['error'] = '模型未给出结论（submit_analysis/skip）'

        result['raw'] = raw_last
        result['latency_ms'] = int((time.time() - started) * 1000)
        return result

    @staticmethod
    def _apply_analysis(args: Dict[str, Any], result: Dict[str, Any]) -> None:
        result['status'] = 'ok'
        result['summary'] = str(args.get('summary') or '')[:2000]
        result['market_view'] = str(args.get('market_view') or '')[:4000]
        result['lessons'] = str(args.get('lessons') or '')[:4000]
        try:
            confidence = float(args.get('confidence')) \
                if args.get('confidence') is not None else None
            if confidence is not None:
                confidence = min(100.0, max(0.0, confidence))
        except (TypeError, ValueError):
            confidence = None
        result['confidence'] = confidence
        picks = []
        risk_flags: List[str] = []
        for i, item in enumerate(args.get('picks') or []):
            if not isinstance(item, dict):
                continue
            code = str(item.get('code') or '').strip().zfill(6)
            if not code.isdigit():
                continue
            action = str(item.get('action') or 'watch').lower()
            if action not in ('buy', 'sell', 'watch', 'avoid'):
                action = 'watch'
            price = _to_float(item.get('price'))
            target = _to_float(item.get('target_price'))
            stop = _to_float(item.get('stop_loss'))
            pick_conf = _to_float(item.get('confidence'))
            if pick_conf is not None:
                pick_conf = min(100.0, max(0.0, pick_conf))
            # 风控校验：买入建议必须给出合理止损/止盈，否则降级为观察。
            if action == 'buy':
                if stop is None or target is None:
                    risk_flags.append(f'{code} 买入缺少止损/止盈，降级为观察')
                    action = 'watch'
                elif price is not None and not (stop < price < target):
                    risk_flags.append(f'{code} 止损/止盈与现价不匹配，降级为观察')
                    action = 'watch'
            picks.append({
                'rank': item.get('rank') or (i + 1),
                'code': code,
                'name': str(item.get('name') or ''),
                'action': action,
                'confidence': pick_conf,
                'price': price,
                'target_price': target,
                'stop_loss': stop,
                'score': _to_float(item.get('score')),
                'sector': str(item.get('sector') or ''),
                'reason': str(item.get('reason') or '')[:1000],
            })
        result['picks'] = picks[:20]
        result['risk_flags'] = risk_flags[:20]
