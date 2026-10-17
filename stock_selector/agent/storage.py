# -*- coding: utf-8 -*-
"""Agent 分析结果的持久化（PostgreSQL）。

复用 :class:`stock_selector.data.postgres_store.PostgresStore` 的连接管理，
新增自己的表：分析批次、个股研判、工具调用轨迹、记忆与战法库。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from stock_selector.data.postgres_store import PostgresStore, _json_safe, _number, Json


AGENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_analyses (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trade_date DATE,
    session TEXT NOT NULL DEFAULT 'intraday',
    trigger TEXT NOT NULL DEFAULT 'interval',
    model TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    summary TEXT,
    market_view TEXT,
    confidence NUMERIC,
    picks_count INTEGER NOT NULL DEFAULT 0,
    rounds INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    prompt_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_analyses_created
    ON agent_analyses (created_at DESC);

CREATE TABLE IF NOT EXISTS agent_picks (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL REFERENCES agent_analyses(id) ON DELETE CASCADE,
    rank INTEGER,
    code VARCHAR(12) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT 'watch',
    confidence NUMERIC,
    price NUMERIC,
    target_price NUMERIC,
    stop_loss NUMERIC,
    score NUMERIC,
    sector TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (analysis_id, code)
);

CREATE INDEX IF NOT EXISTS idx_agent_picks_analysis
    ON agent_picks (analysis_id, rank);

CREATE TABLE IF NOT EXISTS agent_tool_calls (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL REFERENCES agent_analyses(id) ON DELETE CASCADE,
    seq INTEGER,
    round_no INTEGER,
    tool TEXT NOT NULL,
    args JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    ok BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT,
    elapsed_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_analysis
    ON agent_tool_calls (analysis_id, seq);

CREATE TABLE IF NOT EXISTS agent_memory (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_playbook (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    section TEXT NOT NULL DEFAULT 'general',
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_playbook_created
    ON agent_playbook (created_at DESC);

CREATE TABLE IF NOT EXISTS agent_pick_reviews (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT,
    code VARCHAR(12) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT 'buy',
    pick_date DATE,
    pick_price NUMERIC,
    eval_date DATE,
    eval_price NUMERIC,
    ret_pct NUMERIC,
    hit BOOLEAN,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (analysis_id, code, action)
);

CREATE INDEX IF NOT EXISTS idx_agent_pick_reviews_code
    ON agent_pick_reviews (code, pick_date DESC);

CREATE INDEX IF NOT EXISTS idx_agent_pick_reviews_eval
    ON agent_pick_reviews (eval_date DESC);
"""


class AgentStore:
    """Agent 专用仓储。"""

    def __init__(self, store: Optional[PostgresStore] = None):
        self.store = store or PostgresStore()

    # ---------------- schema ----------------

    def ensure_schema(self) -> None:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(AGENT_SCHEMA_SQL)

    def try_ensure_schema(self) -> bool:
        try:
            self.ensure_schema()
            return True
        except Exception as exc:  # noqa: BLE001
            self.store.last_error = str(exc)
            return False

    # ---------------- analyses ----------------

    def save_analysis(self, *, session: str, trigger: str, model: str,
                      status: str, summary: str = '', market_view: str = '',
                      confidence: Optional[float] = None, rounds: int = 0,
                      tool_calls: int = 0, latency_ms: Optional[int] = None,
                      prompt_summary: Optional[Dict[str, Any]] = None,
                      raw_response: Optional[Any] = None,
                      usage: Optional[Dict[str, Any]] = None,
                      error: str = '',
                      picks: Optional[List[Dict[str, Any]]] = None,
                      trace: Optional[List[Dict[str, Any]]] = None,
                      trade_date: Optional[date] = None) -> int:
        picks = list(picks or [])
        trace = list(trace or [])
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_analyses
                    (trade_date, session, trigger, model, status, summary, market_view,
                     confidence, picks_count, rounds, tool_calls, latency_ms,
                     prompt_summary, raw_response, usage, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id""",
                    (trade_date, session, trigger, model, status, summary, market_view,
                     _number(confidence), len(picks), int(rounds), int(tool_calls),
                     latency_ms, Json(_json_safe(prompt_summary or {})),
                     Json(_json_safe(raw_response or {})), Json(_json_safe(usage or {})),
                     error[:2000] if error else ''))
                analysis_id = int(cur.fetchone()[0])
                for idx, pick in enumerate(picks):
                    code = str(pick.get('code') or '').strip().zfill(6)
                    if not code.isdigit():
                        continue
                    try:
                        rank = pick.get('rank')
                        rank = int(rank) if rank is not None else idx + 1
                    except (TypeError, ValueError):
                        rank = idx + 1
                    cur.execute(
                        """INSERT INTO agent_picks
                        (analysis_id, rank, code, name, action, confidence, price,
                         target_price, stop_loss, score, sector, reason)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (analysis_id, code) DO UPDATE SET
                            rank = EXCLUDED.rank, name = EXCLUDED.name,
                            action = EXCLUDED.action, confidence = EXCLUDED.confidence,
                            price = EXCLUDED.price, target_price = EXCLUDED.target_price,
                            stop_loss = EXCLUDED.stop_loss, score = EXCLUDED.score,
                            sector = EXCLUDED.sector, reason = EXCLUDED.reason""",
                        (analysis_id, rank, code, str(pick.get('name') or ''),
                         str(pick.get('action') or 'watch'),
                         _number(pick.get('confidence')), _number(pick.get('price')),
                         _number(pick.get('target_price')), _number(pick.get('stop_loss')),
                         _number(pick.get('score')), str(pick.get('sector') or ''),
                         str(pick.get('reason') or '')[:2000]))
                for seq, item in enumerate(trace, start=1):
                    cur.execute(
                        """INSERT INTO agent_tool_calls
                        (analysis_id, seq, round_no, tool, args, result, ok, error, elapsed_ms)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (analysis_id, seq, int(item.get('round') or 0),
                         str(item.get('tool') or ''), Json(_json_safe(item.get('args') or {})),
                         Json(_json_safe(item.get('result') or {})),
                         bool(item.get('ok', True)), str(item.get('error') or '')[:1000],
                         int(item.get('elapsed_ms') or 0)))
        return analysis_id

    def list_analyses(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, created_at, trade_date, session, trigger, model, status,
                              summary, market_view, confidence, picks_count, rounds,
                              tool_calls, latency_ms, error
                       FROM agent_analyses ORDER BY created_at DESC LIMIT %s""", (limit,))
                return [{
                    'id': r[0], 'created_at': r[1], 'trade_date': str(r[2]) if r[2] else '',
                    'session': r[3], 'trigger': r[4], 'model': r[5], 'status': r[6],
                    'summary': r[7] or '', 'market_view': r[8] or '',
                    'confidence': _number(r[9]), 'picks_count': r[10], 'rounds': r[11],
                    'tool_calls': r[12], 'latency_ms': r[13], 'error': r[14] or '',
                } for r in cur.fetchall()]

    def get_analysis(self, analysis_id: int) -> Optional[Dict[str, Any]]:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, created_at, trade_date, session, trigger, model, status,
                              summary, market_view, confidence, usage, error
                       FROM agent_analyses WHERE id = %s""", (analysis_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    'id': row[0], 'created_at': row[1],
                    'trade_date': str(row[2]) if row[2] else '', 'session': row[3],
                    'trigger': row[4], 'model': row[5], 'status': row[6],
                    'summary': row[7] or '', 'market_view': row[8] or '',
                    'confidence': _number(row[9]), 'usage': row[10], 'error': row[11] or '',
                }

    def get_picks(self, analysis_id: int) -> List[Dict[str, Any]]:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT rank, code, name, action, confidence, price,
                              target_price, stop_loss, score, sector, reason
                       FROM agent_picks WHERE analysis_id = %s
                       ORDER BY rank NULLS LAST, code""", (analysis_id,))
                return [{
                    'rank': r[0], 'code': r[1], 'name': r[2], 'action': r[3],
                    'confidence': _number(r[4]), 'price': _number(r[5]),
                    'target_price': _number(r[6]), 'stop_loss': _number(r[7]),
                    'score': _number(r[8]), 'sector': r[9] or '', 'reason': r[10] or '',
                } for r in cur.fetchall()]

    # ---------------- memory / playbook ----------------

    def get_memory(self) -> Dict[str, Any]:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT key, value, updated_at FROM agent_memory ORDER BY key')
                return {r[0]: {'value': r[1], 'updated_at': str(r[2])}
                        for r in cur.fetchall()}

    def set_memory(self, key: str, value: Any) -> None:
        key = str(key).strip()
        if not key:
            raise ValueError('memory key 不能为空')
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_memory (key, value, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                       updated_at = NOW()""",
                    (key, Json(_json_safe(value))))

    def get_playbook(self) -> Dict[str, Any]:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT section, content FROM agent_playbook
                       ORDER BY created_at DESC LIMIT 20""")
                rows = cur.fetchall()
        result: Dict[str, Any] = {}
        for section, content in rows:
            result.setdefault(section, content)
        return result

    def add_playbook(self, section: str, content: Any, note: str = '') -> None:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_playbook (section, content, note)
                       VALUES (%s, %s, %s)""",
                    (str(section or 'general'), Json(_json_safe(content)), note))

    # ---------------- 研判复盘（结果跟踪） ----------------

    def add_pick_review(self, *, code: str, name: str = '', action: str = 'buy',
                        analysis_id: Optional[int] = None,
                        pick_date: Optional[date] = None, pick_price: Optional[float] = None,
                        eval_date: Optional[date] = None, eval_price: Optional[float] = None,
                        ret_pct: Optional[float] = None, hit: Optional[bool] = None,
                        note: str = '') -> None:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_pick_reviews
                    (analysis_id, code, name, action, pick_date, pick_price,
                     eval_date, eval_price, ret_pct, hit, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (analysis_id, code, action) DO UPDATE SET
                        eval_date = EXCLUDED.eval_date, eval_price = EXCLUDED.eval_price,
                        ret_pct = EXCLUDED.ret_pct, hit = EXCLUDED.hit,
                        note = EXCLUDED.note""",
                    (analysis_id, str(code).zfill(6), name, str(action or 'buy'),
                     pick_date, _number(pick_price), eval_date, _number(eval_price),
                     _number(ret_pct), hit, note[:500]))

    def unreviewed_picks(self, *, lookback_days: int = 15, limit: int = 200) -> List[Dict[str, Any]]:
        """返回近期尚无复盘记录、且带价格的 buy 研判。"""
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT p.analysis_id, p.code, p.name, p.action, p.price,
                              COALESCE(a.trade_date, a.created_at::date) AS pick_date
                       FROM agent_picks p
                       JOIN agent_analyses a ON a.id = p.analysis_id
                       LEFT JOIN agent_pick_reviews r
                              ON r.analysis_id = p.analysis_id AND r.code = p.code
                             AND r.action = p.action
                       WHERE p.action = 'buy' AND p.price IS NOT NULL
                         AND r.id IS NULL
                         AND COALESCE(a.trade_date, a.created_at::date)
                             >= CURRENT_DATE - %s
                       ORDER BY a.created_at DESC
                       LIMIT %s""",
                    (int(lookback_days), int(limit)))
                return [{'analysis_id': r[0], 'code': r[1], 'name': r[2] or '',
                         'action': r[3], 'price': _number(r[4]),
                         'pick_date': r[5]} for r in cur.fetchall()]

    def list_pick_reviews(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT analysis_id, code, name, action, pick_date, pick_price,
                              eval_date, eval_price, ret_pct, hit, note
                       FROM agent_pick_reviews
                       ORDER BY eval_date DESC NULLS LAST, created_at DESC LIMIT %s""",
                    (int(limit),))
                return [{
                    'analysis_id': r[0], 'code': r[1], 'name': r[2] or '',
                    'action': r[3], 'pick_date': str(r[4]) if r[4] else '',
                    'pick_price': _number(r[5]), 'eval_date': str(r[6]) if r[6] else '',
                    'eval_price': _number(r[7]), 'ret_pct': _number(r[8]),
                    'hit': r[9], 'note': r[10] or '',
                } for r in cur.fetchall()]

    def performance_summary(self, days: int = 30) -> Dict[str, Any]:
        """汇总近期研判胜率与平均收益，供提示词注入与展示。"""
        with self.store.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*),
                              COUNT(*) FILTER (WHERE hit),
                              AVG(ret_pct),
                              AVG(ret_pct) FILTER (WHERE hit),
                              AVG(ret_pct) FILTER (WHERE NOT hit)
                       FROM agent_pick_reviews
                       WHERE eval_date >= CURRENT_DATE - %s AND ret_pct IS NOT NULL""",
                    (int(days),))
                row = cur.fetchone() or (0, 0, None, None, None)
        total = int(row[0] or 0)
        hits = int(row[1] or 0)
        avg = _number(row[2])
        avg_win = _number(row[3])
        avg_loss = _number(row[4])
        return {
            'days': int(days), 'total': total, 'hits': hits,
            'win_rate': round(hits / total * 100, 1) if total else None,
            'avg_ret_pct': round(avg, 2) if avg is not None else None,
            'avg_win_pct': round(avg_win, 2) if avg_win is not None else None,
            'avg_loss_pct': round(avg_loss, 2) if avg_loss is not None else None,
        }
