"""PostgreSQL storage for daily selections and grouped watchlists.

The database is optional at runtime.  Set ``STOCK_SELECTOR_PG_DSN`` or the
``STOCK_SELECTOR_PG*`` environment variables before using the persistence
features.  The module never stores credentials in the source tree.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime
import json
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

try:
    import psycopg2
    from psycopg2.extras import Json
except ImportError:  # pragma: no cover - handled as a friendly runtime error
    psycopg2 = None
    Json = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS selection_runs (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    source TEXT,
    selected_count INTEGER NOT NULL DEFAULT 0,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (trade_date, category, strategy_id, generated_at)
);

CREATE INDEX IF NOT EXISTS idx_selection_runs_trade_date
    ON selection_runs (trade_date DESC);

CREATE TABLE IF NOT EXISTS daily_selections (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES selection_runs(id) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    code VARCHAR(12) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    price NUMERIC,
    change_pct NUMERIC,
    turnover NUMERIC,
    volume_ratio NUMERIC,
    score NUMERIC,
    signal_date DATE,
    explanation TEXT,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, code)
);

CREATE INDEX IF NOT EXISTS idx_daily_selections_date_code
    ON daily_selections (trade_date DESC, code);

ALTER TABLE daily_selections ADD COLUMN IF NOT EXISTS volume NUMERIC;
ALTER TABLE daily_selections ADD COLUMN IF NOT EXISTS amount NUMERIC;
ALTER TABLE daily_selections ADD COLUMN IF NOT EXISTS outer_ratio NUMERIC;
ALTER TABLE daily_selections ADD COLUMN IF NOT EXISTS sector TEXT;

CREATE TABLE IF NOT EXISTS watchlist_groups (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watchlist_stocks (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES watchlist_groups(id) ON DELETE CASCADE,
    code VARCHAR(12) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (group_id, code)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_stocks_group
    ON watchlist_stocks (group_id, code);

CREATE TABLE IF NOT EXISTS trading_accounts (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL DEFAULT 'manual',
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trade_orders (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    code VARCHAR(12) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    action VARCHAR(6) NOT NULL,
    price NUMERIC,
    volume INTEGER,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_orders_account
    ON trade_orders (account_id, created_at DESC);
"""


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe Python values."""
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
            return None
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        return value.item()
    except AttributeError:
        return str(value)


def _number(value: Any) -> Optional[float]:
    if value in (None, ''):
        return None
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


class PostgresStore:
    """Small repository used by the GUI, CLI and batch runner."""

    def __init__(self, dsn: Optional[str] = None, connect_timeout: int = 2):
        self.dsn = dsn or os.getenv('STOCK_SELECTOR_PG_DSN') or self._default_dsn()
        self.connect_timeout = int(connect_timeout)
        self.last_error: Optional[str] = None

    @staticmethod
    def _default_dsn() -> str:
        parts = {
            'host': os.getenv('STOCK_SELECTOR_PGHOST', '127.0.0.1'),
            'port': os.getenv('STOCK_SELECTOR_PGPORT', '5432'),
            'dbname': os.getenv('STOCK_SELECTOR_PGDATABASE', 'stock_selector'),
            'user': os.getenv('STOCK_SELECTOR_PGUSER', 'postgres'),
        }
        password = (os.getenv('STOCK_SELECTOR_PGPASSWORD')
                    or os.getenv('PGPASSWORD')
                    or 'root')
        parts['password'] = password
        return ' '.join(f'{key}={value}' for key, value in parts.items())

    def _connect(self):
        if psycopg2 is None:
            raise RuntimeError('未安装 psycopg2，请执行: pip install psycopg2-binary')
        return psycopg2.connect(self.dsn, connect_timeout=self.connect_timeout)

    @contextmanager
    def connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
            self.last_error = None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)

    def try_ensure_schema(self) -> bool:
        try:
            self.ensure_schema()
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            return False

    def save_selection_run(
        self,
        *,
        trade_date: date,
        category: str,
        strategy_id: str,
        strategy_name: str,
        source: Optional[str],
        rows: Iterable[Dict[str, Any]],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> int:
        rows = list(rows)
        safe_parameters = _json_safe(parameters or {})
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO selection_runs
                    (trade_date, category, strategy_id, strategy_name, source,
                     selected_count, parameters)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id""",
                    (trade_date, category, strategy_id, strategy_name, source,
                     len(rows), Json(safe_parameters)),
                )
                run_id = cur.fetchone()[0]
                for row in rows:
                    code = row.get('代码', row.get('code', ''))
                    name = row.get('名称', row.get('name', ''))
                    price = row.get('价格', row.get('price'))
                    change_pct = row.get('涨跌幅%', row.get('change_pct'))
                    turnover = row.get('换手%', row.get('turnover'))
                    volume_ratio = row.get('量比', row.get('volume_ratio'))
                    score = row.get('评分', row.get('score'))
                    signal_date = row.get('日期') or row.get('latest_date')
                    explanation = row.get('说明', row.get('reason', ''))
                    try:
                        if signal_date:
                            signal_date = date.fromisoformat(str(signal_date)[:10])
                    except ValueError:
                        signal_date = None
                    cur.execute(
                        """INSERT INTO daily_selections
                        (run_id, trade_date, code, name, price, change_pct,
                         turnover, volume_ratio, volume, amount, outer_ratio, sector, score,
                         signal_date, explanation, raw_data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (run_id, code) DO UPDATE SET
                            name = EXCLUDED.name, price = EXCLUDED.price,
                            change_pct = EXCLUDED.change_pct, turnover = EXCLUDED.turnover,
                            volume_ratio = EXCLUDED.volume_ratio, volume = EXCLUDED.volume,
                            amount = EXCLUDED.amount, outer_ratio = EXCLUDED.outer_ratio,
                            sector = EXCLUDED.sector,
                            score = EXCLUDED.score,
                            signal_date = EXCLUDED.signal_date, explanation = EXCLUDED.explanation,
                            raw_data = EXCLUDED.raw_data""",
                        (run_id, trade_date, str(code).zfill(6), str(name), _number(price),
                         _number(change_pct), _number(turnover), _number(volume_ratio),
                         _number(row.get('成交量', row.get('volume'))),
                         _number(row.get('成交额(亿)', row.get('成交额', row.get('amount')))),
                         _number(row.get('外盘%', row.get('outer_ratio'))),
                         str(row.get('行业/板块', row.get('sector', ''))),
                         _number(score), signal_date, str(explanation), Json(_json_safe(row))),
                    )
        return int(run_id)

    def list_groups(self) -> list[Dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, name, created_at FROM watchlist_groups ORDER BY name')
                return [{'id': row[0], 'name': row[1], 'created_at': row[2]} for row in cur.fetchall()]

    def create_group(self, name: str) -> Dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError('分组名称不能为空')
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO watchlist_groups (name) VALUES (%s) '
                    'ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name '
                    'RETURNING id, name, created_at', (name,))
                row = cur.fetchone()
                return {'id': row[0], 'name': row[1], 'created_at': row[2]}

    def add_stock(self, group_name: str, code: str, name: str = '', note: str = '') -> None:
        code = str(code).strip().zfill(6)
        if not code.isdigit():
            raise ValueError('股票代码必须是数字')
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM watchlist_groups WHERE name = %s', (group_name,))
                group = cur.fetchone()
                if not group:
                    raise ValueError(f'分组不存在: {group_name}')
                cur.execute(
                    """INSERT INTO watchlist_stocks (group_id, code, name, note)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (group_id, code) DO UPDATE SET name = EXCLUDED.name, note = EXCLUDED.note""",
                    (group[0], code, name or '', note or ''),
                )

    def remove_stock(self, group_name: str, code: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM watchlist_stocks ws USING watchlist_groups wg
                    WHERE ws.group_id = wg.id AND wg.name = %s AND ws.code = %s""",
                    (group_name, str(code).strip().zfill(6)),
                )

    def list_stocks(self, group_name: str) -> list[Dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ws.code, ws.name, ws.note, ws.added_at
                    FROM watchlist_stocks ws JOIN watchlist_groups wg ON wg.id = ws.group_id
                    WHERE wg.name = %s ORDER BY ws.code""", (group_name,))
                return [dict(code=row[0], name=row[1], note=row[2], added_at=row[3])
                        for row in cur.fetchall()]

    # ---------------- AI 交易 ----------------

    def upsert_account(self, name: str, channel: str,
                       settings: Optional[Dict[str, Any]] = None) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO trading_accounts (name, channel, settings)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (name) DO UPDATE
                    SET channel = EXCLUDED.channel, settings = EXCLUDED.settings
                    RETURNING id""",
                    (name, channel, Json(_json_safe(settings or {}))))
                return cur.fetchone()[0]

    def list_accounts(self) -> list[Dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, name, channel, settings FROM trading_accounts ORDER BY id')
                return [{'id': r[0], 'name': r[1], 'channel': r[2], 'settings': r[3]}
                        for r in cur.fetchall()]

    def get_account(self, name: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, name, channel, settings FROM trading_accounts WHERE name = %s', (name,))
                row = cur.fetchone()
                if not row:
                    return None
                return {'id': row[0], 'name': row[1], 'channel': row[2], 'settings': row[3]}

    def save_order(self, account_id: int, *, code: str, name: str, action: str,
                   price: Optional[float], volume: int, reason: str = '') -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO trade_orders
                    (account_id, code, name, action, price, volume, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (account_id, code, name, action, price, volume, reason))
                return cur.fetchone()[0]

    def list_orders(self, account_id: Optional[int] = None,
                    limit: int = 100) -> list[Dict[str, Any]]:
        sql = """SELECT o.id, a.name AS account, o.code, o.name AS stock_name,
                 o.action, o.price, o.volume, o.reason, o.status, o.created_at
                 FROM trade_orders o JOIN trading_accounts a ON a.id = o.account_id"""
        params: list[Any] = []
        if account_id is not None:
            sql += ' WHERE o.account_id = %s'
            params.append(account_id)
        sql += ' ORDER BY o.created_at DESC LIMIT %s'
        params.append(limit)
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [{'id': r[0], 'account': r[1], 'code': r[2], 'name': r[3],
                         'action': r[4], 'price': r[5], 'volume': r[6],
                         'reason': r[7], 'status': r[8], 'created_at': r[9]}
                        for r in cur.fetchall()]

    def update_order_status(self, order_id: int, status: str,
                            result: Optional[Dict[str, Any]] = None) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE trade_orders
                    SET status = %s, result = %s, updated_at = NOW()
                    WHERE id = %s""",
                    (status, Json(_json_safe(result or {})), order_id))

    # ---------------- 选股批次查询 ----------------

    def list_run_dates(self, limit: int = 30) -> list[str]:
        """有选股记录的交易日（最近在前）。"""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT DISTINCT trade_date FROM selection_runs '
                    'ORDER BY trade_date DESC LIMIT %s', (limit,))
                return [str(row[0]) for row in cur.fetchall()]

    def list_run_categories(self) -> list[str]:
        """数据库中出现过的策略类别（去重）。"""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT DISTINCT category FROM selection_runs ORDER BY category')
                return [row[0] for row in cur.fetchall()]

    def list_run_strategies(self, category: Optional[str] = None) -> list[Dict[str, Any]]:
        """列出一个类别下出现过的策略（含最近批次时间，按时间倒序）。"""
        sql = ('SELECT strategy_id, strategy_name, MAX(generated_at) AS last_at '
               'FROM selection_runs ')
        params: tuple = ()
        if category:
            sql += 'WHERE category = %s '
            params = (category,)
        sql += 'GROUP BY strategy_id, strategy_name ORDER BY last_at DESC'
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [{'strategy_id': row[0], 'strategy_name': row[1], 'last_at': row[2]}
                        for row in cur.fetchall()]

    def list_runs(self, trade_date: Optional[str] = None,
                  category: Optional[str] = None,
                  strategy_id: Optional[str] = None,
                  limit: int = 200) -> list[Dict[str, Any]]:
        """按 日期/类别/策略 组合条件列出选股批次（最近在前）。

        任一参数为 None/空 表示不限制该维度。
        """
        where, params = [], []
        if trade_date:
            where.append('trade_date = %s')
            params.append(trade_date)
        if category:
            where.append('category = %s')
            params.append(category)
        if strategy_id:
            where.append('strategy_id = %s')
            params.append(strategy_id)
        sql = ('SELECT id, trade_date, generated_at, category, strategy_id, '
               'strategy_name, source, selected_count, parameters FROM selection_runs ')
        if where:
            sql += 'WHERE ' + ' AND '.join(where) + ' '
        sql += 'ORDER BY generated_at DESC LIMIT %s'
        params.append(limit)
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [self._run_from_row(row) for row in cur.fetchall()]

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """按批次 ID 查询批次信息。"""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT id, trade_date, generated_at, category, strategy_id, '
                    'strategy_name, source, selected_count, parameters '
                    'FROM selection_runs WHERE id = %s', (run_id,))
                row = cur.fetchone()
                return self._run_from_row(row) if row else None

    def fetch_run_rows(self, run_id: int) -> list[Dict[str, Any]]:
        """查询某个批次的全部股票明细（按评分倒序）。"""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT code, name, price, change_pct, turnover, volume_ratio,
                              volume, amount, outer_ratio, sector, score, signal_date, explanation
                       FROM daily_selections WHERE run_id = %s
                       ORDER BY score DESC NULLS LAST, code""", (run_id,))
                return [{'code': row[0], 'name': row[1], 'price': _number(row[2]),
                         'change_pct': _number(row[3]), 'turnover': _number(row[4]),
                         'volume_ratio': _number(row[5]), 'volume': _number(row[6]),
                         'amount': _number(row[7]), 'outer_ratio': _number(row[8]),
                         'sector': row[9] or '', 'score': _number(row[10]),
                         'signal_date': str(row[11]) if row[11] else '', 'explanation': row[12]}
                        for row in cur.fetchall()]

    @staticmethod
    def _run_from_row(row) -> Dict[str, Any]:
        return {'id': row[0], 'trade_date': str(row[1]), 'generated_at': row[2],
                'category': row[3], 'strategy_id': row[4], 'strategy_name': row[5],
                'source': row[6], 'selected_count': row[7], 'parameters': row[8]}


def _disp_width(text) -> int:
    """字符显示宽度（中文等 CJK 宽字符按 2 列计）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in str(text))


def _pad_r(text, width) -> str:
    text = str(text)
    return text + ' ' * max(0, width - _disp_width(text))


def _pad_l(text, width) -> str:
    text = str(text)
    return ' ' * max(0, width - _disp_width(text)) + text


def _trunc(text, width) -> str:
    text = str(text)
    if _disp_width(text) <= width:
        return text
    out, used = '', 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + '…'


def _num_text(value) -> str:
    return '' if value is None else f'{value:.2f}'


def _print_runs(runs) -> None:
    print(f'共 {len(runs)} 个批次：')
    widths = (8, 12, 26, 10, 26, 6, 10)
    header = ' | '.join(
        _pad_r(text, width) for text, width in
        zip(('批次ID', '交易日', '生成时间', '类别', '策略', '数量', '数据源'), widths))
    print(header)
    for run in runs:
        cells = (str(run['id']), run['trade_date'], str(run['generated_at']),
                 run['category'], run['strategy_id'], str(run['selected_count'] or 0),
                 run['source'] or '')
        print(' | '.join(_pad_r(text, width) for text, width in zip(cells, widths)))


def _print_run_rows(run, rows) -> None:
    print('-' * 78)
    declared = int(run['selected_count'] or 0)
    print(f"批次 #{run['id']}  {run['trade_date']}  {run['generated_at']}  "
          f"类别={run['category']}  策略={run['strategy_id']}（{run['strategy_name']}）  "
          f"数据源={run['source'] or ''}  声明{declared}只，查询到{len(rows)}行")
    widths = (8, 12, 9, 8, 7, 6, 6, 12, 40)
    header = (' ' + _pad_r('代码', 8) + ' ' + _pad_r('名称', 12) + ' ' + _pad_l('价格', 9) +
              ' ' + _pad_l('涨跌幅%', 8) + ' ' + _pad_l('换手%', 7) + ' ' + _pad_l('量比', 6) +
              ' ' + _pad_l('评分', 6) + ' ' + _pad_r('日期', 12) + ' ' + _pad_r('说明', 40))
    print(header)
    for row in rows:
        cols = (row['code'], row['name'] or '', _num_text(row['price']),
                _num_text(row['change_pct']), _num_text(row['turnover']),
                _num_text(row['volume_ratio']), _num_text(row['score']),
                row['signal_date'] or '', row['explanation'] or '')
        print(' ' + _pad_r(cols[0], 8) + ' ' + _pad_r(cols[1], 12)
              + ' ' + _pad_l(cols[2], 9) + ' ' + _pad_l(cols[3], 8)
              + ' ' + _pad_l(cols[4], 7) + ' ' + _pad_l(cols[5], 6)
              + ' ' + _pad_l(cols[6], 6) + ' ' + _pad_r(cols[7], 12)
              + ' ' + _trunc(cols[8], 40))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m stock_selector.data.postgres_store',
        description='stock_selector PostgreSQL 数据管理：初始化表结构，按 日期/类别/策略 查询选股批次。')
    sub = parser.add_subparsers(dest='command')

    p_init = sub.add_parser('init', help='创建/更新表结构')
    p_init.add_argument('--dsn')

    p_list = sub.add_parser('list', help='列出批次（可按 日期/类别/策略 过滤）')
    p_list.add_argument('--dsn')
    p_list.add_argument('--date', default='', help='交易日，如 2026-10-13')
    p_list.add_argument('--category', default='', help='策略类别，如 常规 / 技术 / v2')
    p_list.add_argument('--strategy', default='', help='策略 ID，如 default / ma_trend')
    p_list.add_argument('--limit', type=int, default=50)

    p_query = sub.add_parser('query', help='查询批次股票明细（指定 --run 或按条件过滤）')
    p_query.add_argument('--dsn')
    p_query.add_argument('--date', default='')
    p_query.add_argument('--category', default='')
    p_query.add_argument('--strategy', default='')
    p_query.add_argument('--run', type=int, default=0, help='批次ID（指定后忽略过滤条件）')
    p_query.add_argument('--csv', default='', help='同时导出到 CSV 文件路径')

    args = parser.parse_args(argv)

    if args.command is None:
        args.command = 'init'

    store = PostgresStore(args.dsn)
    if not store.try_ensure_schema():
        print(f'数据库连接失败：{store.last_error}')
        return 1

    if args.command == 'init':
        print('PostgreSQL 表结构初始化完成。')
        return 0

    if args.command == 'list':
        runs = store.list_runs(trade_date=args.date or None,
                               category=args.category or None,
                               strategy_id=args.strategy or None, limit=args.limit)
        if not runs:
            print('未找到匹配的选股批次。')
            return 0
        _print_runs(runs)
        return 0

    if args.command == 'query':
        if args.run:
            run = store.get_run(args.run)
            runs = [run] if run else []
        else:
            runs = store.list_runs(trade_date=args.date or None,
                                   category=args.category or None,
                                   strategy_id=args.strategy or None, limit=200)
        if not runs:
            print('未找到匹配的选股批次。')
            return 0
        exported = 0
        for run in runs:
            rows = store.fetch_run_rows(run['id'])
            _print_run_rows(run, rows)
            if args.csv:
                import csv
                with open(args.csv, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(['代码', '名称', '价格', '涨跌幅%', '换手%', '量比', '评分', '日期', '说明'])
                    for row in rows:
                        writer.writerow([row['code'], row['name'], row['price'], row['change_pct'],
                                         row['turnover'], row['volume_ratio'], row['score'],
                                         row['signal_date'], row['explanation']])
                    exported += 1
        if exported:
            print(f'\n已导出到：{args.csv}')
        return 0

    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
