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
