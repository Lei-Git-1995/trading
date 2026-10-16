# -*- coding: utf-8 -*-
"""Agent 运行入口与调度器。

- :func:`run_analysis_once`：执行一次「准备数据 → ReAct 分析 → 入库」。
- :class:`AgentScheduler`：后台线程，盘中按间隔分析，并在每日学习时段触发一次。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from stock_selector.agent import config as agent_config
from stock_selector.agent.llm import LLMClient
from stock_selector.agent.loop import ReActAgent
from stock_selector.agent.tools import ToolContext
from stock_selector.utils import app_config


def load_candidates(store, limit: int = 20,
                    trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """从当日选股批次中汇总候选股票（按评分倒序、去重）。"""
    if store is None:
        return []
    try:
        dates = store.list_run_dates(limit=10)
    except Exception:  # noqa: BLE001
        return []
    if not dates:
        return []
    target = trade_date or dates[0]
    try:
        runs = store.list_runs(trade_date=target, limit=80)
    except Exception:  # noqa: BLE001
        return []
    rows: List[Dict[str, Any]] = []
    seen = set()
    for run in runs:
        try:
            run_rows = store.fetch_run_rows(run['id'])
        except Exception:  # noqa: BLE001
            continue
        for row in run_rows:
            code = str(row.get('code') or '')
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(row)
    rows.sort(key=lambda r: (r.get('score') or 0), reverse=True)
    return rows[:limit]


def run_analysis_once(*, store, agent_store,
                      llm_settings: Optional[Dict[str, Any]] = None,
                      agent_cfg: Optional[Dict[str, Any]] = None,
                      trigger: str = 'manual',
                      session: str = 'intraday', log: Callable[[str], None] = print,
                      persist: bool = True) -> Dict[str, Any]:
    """执行一次完整分析，返回结果 dict（含 analysis_id）。"""
    cfg = agent_config.merge_config(agent_cfg)
    llm_settings = llm_settings if llm_settings is not None else app_config.get_llm_config()

    llm = LLMClient(llm_settings, cfg)
    if not llm.enabled:
        log('[agent] 大模型未启用，跳过分析。请在「配置」页勾选「启用大模型」。')
        return {'status': 'error', 'error': '大模型未启用', 'picks': [], 'trace': [],
                'model': llm.model_trade}
    if not llm.available:
        log('[agent] 未配置 API Key，跳过分析。请在「配置」页填写并保存。')
        return {'status': 'error', 'error': '未配置 API Key', 'picks': [], 'trace': [],
                'model': llm.model_trade}

    candidates = load_candidates(store, int(cfg.get('candidates_limit') or 20))
    log(f'[agent] 候选 {len(candidates)} 只，模型 {llm.model_trade if session != "learn" else llm.model_learn}')

    account = store.get_account('模拟盘') if store else None
    ctx = ToolContext(store=store, agent_store=agent_store, account=account,
                      candidates=candidates, log=log)
    agent = ReActAgent(llm, ctx, cfg, log=log)
    kind = 'learn' if session == 'learn' else 'trade'
    result = agent.run(session=session, trigger=trigger, kind=kind)
    result['session'] = session
    result['trigger'] = trigger
    result['candidate_codes'] = [str(row.get('code') or '').zfill(6) for row in candidates]

    if persist and agent_store is not None:
        try:
            analysis_id = agent_store.save_analysis(
                session=session, trigger=trigger, model=result.get('model') or '',
                status=result.get('status') or 'error', summary=result.get('summary') or '',
                market_view=result.get('market_view') or '',
                confidence=result.get('confidence'), rounds=result.get('rounds') or 0,
                tool_calls=result.get('tool_calls') or 0,
                latency_ms=result.get('latency_ms'),
                prompt_summary={'candidate_count': len(candidates),
                                'goal': result.get('goal') or ''},
                raw_response=result.get('raw') or {},
                usage=result.get('usage') or {},
                error=result.get('error') or '',
                picks=result.get('picks') or [],
                trace=result.get('trace') or [],
                trade_date=agent_config.today())
            result['analysis_id'] = analysis_id
            if result.get('lessons'):
                try:
                    agent_store.set_memory('last_lessons', {
                        'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'session': session, 'text': result.get('lessons')})
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            log(f'[agent] 结果入库失败: {exc}')
            result['error'] = (result.get('error') or '') + f' | 入库失败: {exc}'

    log(f'[agent] 完成 status={result.get("status")} picks={len(result.get("picks") or [])}')
    return result


class AgentScheduler:
    """后台调度：盘中定期分析 + 每日学习时段。"""

    def __init__(self, *, store, agent_store,
                 llm_settings: Optional[Dict[str, Any]] = None,
                 agent_cfg: Optional[Dict[str, Any]] = None,
                 log: Callable[[str], None] = print,
                 on_result: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.store = store
        self.agent_store = agent_store
        self.llm_settings = llm_settings if llm_settings is not None else app_config.get_llm_config()
        self.cfg = agent_config.merge_config(agent_cfg)
        self.log = log
        self.on_result = on_result
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_intraday = 0.0
        self._learn_done: Dict[str, str] = {}   # slot -> date
        self.last_result: Optional[Dict[str, Any]] = None

    # ---------------- 生命周期 ----------------

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._last_intraday = time.time()   # 启动后等一个间隔再首跑
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='agent-scheduler')
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    # ---------------- 主循环 ----------------

    def _loop(self) -> None:
        self.log('[agent] 调度器已启动')
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                self.log(f'[agent] 调度异常: {exc}')
            self._stop.wait(10)
        self.log('[agent] 调度器已停止')

    def _tick(self) -> None:
        now = datetime.now()
        cfg = self.cfg
        interval = max(30, int(cfg.get('interval_sec') or 300))

        if agent_config.in_trading_session(now, cfg.get('sessions')):
            if time.time() - self._last_intraday >= interval:
                self._last_intraday = time.time()
                self._execute(trigger='interval', session='intraday')

        slot = agent_config.current_learn_slot(now, cfg.get('learn_slots'))
        if slot:
            today = now.strftime('%Y-%m-%d')
            if self._learn_done.get(slot) != today:
                self._learn_done[slot] = today
                self._execute(trigger='learn', session='learn')

    def _execute(self, *, trigger: str, session: str) -> None:
        self.log(f'[agent] 触发 {trigger}/{session} 分析…')
        result = run_analysis_once(
            store=self.store, agent_store=self.agent_store,
            llm_settings=self.llm_settings, agent_cfg=self.cfg,
            trigger=trigger, session=session, log=self.log, persist=True)
        self.last_result = result
        account = self.store.get_account('模拟盘') if self.store else None
        settings = (account or {}).get('settings') or {}
        if account and settings.get('auto_paper_enabled') and session == 'intraday':
            try:
                from stock_selector.trading.auto_trader import PaperAutoTrader
                outcome = PaperAutoTrader(self.store, account, settings, log=self.log).run(result)
                result['paper_trades'] = outcome
                self.log(f"[paper] 自动交易：成交 {len(outcome.get('executed') or [])} 笔，拦截 {len(outcome.get('blocked') or [])} 笔")
            except Exception as exc:  # noqa: BLE001
                result['paper_trade_error'] = str(exc)
                self.log(f'[paper] 自动交易周期失败：{exc}')
        if self.on_result:
            try:
                self.on_result(result)
            except Exception:  # noqa: BLE001
                pass
