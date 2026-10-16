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


def _system_prompt() -> str:
    lines = [
        '你是 A 股短线研判 Agent，拥有取证工具，负责给出「大盘研判 + 个股排序」。',
        '重要：你只做分析，不直接下单；输出供人工参考。',
        '工作方式：先调用取证工具了解大盘/板块/候选/资金，再给出结论。',
        '规则：',
        '1) 结论必须基于工具返回的数据，不得编造行情；',
        '2) 每轮可调用多个工具，但请节约调用；',
        '3) 必须且只能通过 submit_analysis 或 skip 结束本轮；',
        '4) 候选股票请给出 1~8 只，按 rank 排序，action∈{buy,sell,watch,avoid}。',
        '5) 盘中决策必须先读取持仓并用 read_trade_history 复盘已完成交易，再输出持仓卖出或新候选买入意见；学习批次总结近期盈亏和失误，不直接产生交易。',
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
        memory = {}
        playbook = {}
        try:
            if ctx.agent_store:
                memory = ctx.agent_store.get_memory()
                playbook = ctx.agent_store.get_playbook()
        except Exception:  # noqa: BLE001
            pass
        return {
            'session': session,
            'trigger': trigger,
            'date': time.strftime('%Y-%m-%d'),
            'time': time.strftime('%H:%M:%S'),
            'candidate_count': len(ctx.candidates or []),
            'candidates': candidates,
            'memory': list(memory.keys()),
            'playbook_sections': list(playbook.keys()),
            'max_react_rounds': self.max_rounds,
            'note': '如需完整记忆/战法内容请调用 read_memory / read_playbook。',
        }

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
            result['confidence'] = float(args.get('confidence')) \
                if args.get('confidence') is not None else None
        except (TypeError, ValueError):
            result['confidence'] = None
        picks = []
        for i, item in enumerate(args.get('picks') or []):
            if not isinstance(item, dict):
                continue
            code = str(item.get('code') or '').strip().zfill(6)
            if not code.isdigit():
                continue
            action = str(item.get('action') or 'watch').lower()
            if action not in ('buy', 'sell', 'watch', 'avoid'):
                action = 'watch'
            picks.append({
                'rank': item.get('rank') or (i + 1),
                'code': code,
                'name': str(item.get('name') or ''),
                'action': action,
                'confidence': item.get('confidence'),
                'price': item.get('price'),
                'target_price': item.get('target_price'),
                'stop_loss': item.get('stop_loss'),
                'score': item.get('score'),
                'sector': str(item.get('sector') or ''),
                'reason': str(item.get('reason') or ''),
            })
        result['picks'] = picks[:20]
