"""Persist closed OKX Demo 15m candles from REST and business WebSocket."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import ccxt
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "user_data" / "market_data.sqlite"
REST_HOST = "openapi.okx.com"
WS_URL = "wss://wspap.okx.com:8443/ws/v5/business"
PAIR_MAP = {"BTC-USDT-SWAP": "BTC/USDT:USDT", "ETH-USDT-SWAP": "ETH/USDT:USDT"}
TIMEFRAME = "15m"
INTERVAL_MS = 15 * 60 * 1000
LOG = logging.getLogger("okx_market_recorder")


def setup_logging() -> None:
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    LOG.addHandler(stream)
    path = ROOT / "user_data" / "logs" / "market-recorder.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOG.addHandler(file_handler)


def connect_db(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("""CREATE TABLE IF NOT EXISTS candles (
        inst_id TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        ts_ms INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        source TEXT NOT NULL,
        raw_json TEXT NOT NULL,
        received_at TEXT NOT NULL,
        PRIMARY KEY (inst_id, timeframe, ts_ms)
    )""")
    db.commit()
    return db


def save_candle(db: sqlite3.Connection, inst_id: str, values: list, source: str) -> bool:
    if len(values) < 6 or inst_id not in PAIR_MAP:
        return False
    ts_ms = int(values[0])
    if ts_ms <= 0 or ts_ms + INTERVAL_MS > int(time.time() * 1000):
        return False  # current, incomplete candle
    prices = [float(value) for value in values[1:6]]
    if min(prices[:4]) <= 0 or prices[4] < 0:
        return False
    db.execute("""INSERT INTO candles
        (inst_id, timeframe, ts_ms, open, high, low, close, volume, source, raw_json, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(inst_id, timeframe, ts_ms) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low,
            close=excluded.close, volume=excluded.volume,
            source=excluded.source, raw_json=excluded.raw_json,
            received_at=excluded.received_at""",
        (inst_id, TIMEFRAME, ts_ms, *prices, source, json.dumps(values, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return True


def latest_ts(db: sqlite3.Connection, inst_id: str) -> int | None:
    row = db.execute("SELECT MAX(ts_ms) FROM candles WHERE inst_id=? AND timeframe=?", (inst_id, TIMEFRAME)).fetchone()
    return row[0] if row else None



def backfill_start(last: int | None, end_ms: int, initial_days: int, force_initial: bool) -> int:
    initial_start = end_ms - initial_days * 86_400_000
    if last is None:
        return initial_start
    recent_start = max(0, last - 86_400_000)
    return min(recent_start, initial_start) if force_initial else recent_start
def backfill(db: sqlite3.Connection, proxy: str | None, initial_days: int,
             force_initial: bool = False) -> None:
    config = {
        "hostname": REST_HOST,
        "urls": {"api": {"rest": "https://openapi.okx.com"}},
        "options": {"defaultType": "swap", "sandboxMode": True},
        "headers": {"x-simulated-trading": "1"},
        "enableRateLimit": True,
        "timeout": 15000,
    }
    if proxy:
        config["httpsProxy"] = proxy
    exchange = ccxt.okx(config)
    try:
        exchange.load_markets()
        end_ms = int(time.time() * 1000) - INTERVAL_MS
        for inst_id, symbol in PAIR_MAP.items():
            last = latest_ts(db, inst_id)
            start_ms = backfill_start(last, end_ms, initial_days, force_initial)
            count = 0
            while start_ms <= end_ms:
                batch = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, since=start_ms, limit=300)
                if not batch:
                    break
                for candle in batch:
                    if save_candle(db, inst_id, candle, "REST"):
                        count += 1
                next_ms = max(int(item[0]) for item in batch) + INTERVAL_MS
                if next_ms <= start_ms:
                    break
                start_ms = next_ms
                if len(batch) < 300:
                    break
            LOG.info("REST backfill %s: %d closed candles", inst_id, count)
    finally:
        exchange.close()



def process_ws_message(db: sqlite3.Connection, message: dict) -> int:
    if message.get("event") == "error":
        raise RuntimeError(f"WS subscription error: {message}")
    inst_id = message.get("arg", {}).get("instId")
    saved = 0
    for candle in message.get("data", []):
        if inst_id in PAIR_MAP and len(candle) >= 9 and str(candle[-1]) == "1":
            if save_candle(db, inst_id, candle, "WS"):
                LOG.info("Saved %s closed candle %s", inst_id, candle[0])
                saved += 1
    return saved


def stream(db: sqlite3.Connection, proxy: str | None) -> None:
    with connect(WS_URL, proxy=proxy, open_timeout=15, close_timeout=5, ping_interval=None) as ws:
        args = [{"channel": "candle15m", "instId": inst_id} for inst_id in PAIR_MAP]
        ws.send(json.dumps({"op": "subscribe", "args": args}))
        LOG.info("Connected OKX Demo business WS for %s", ", ".join(PAIR_MAP))
        while True:
            try:
                payload = ws.recv(timeout=20)
            except TimeoutError:
                ws.send("ping")
                continue
            if payload == "pong":
                continue
            process_ws_message(db, json.loads(payload))


def status(db: sqlite3.Connection) -> None:
    for inst_id in PAIR_MAP:
        row = db.execute("SELECT COUNT(*), MIN(ts_ms), MAX(ts_ms) FROM candles WHERE inst_id=? AND timeframe=?",
                         (inst_id, TIMEFRAME)).fetchone()
        count, first, last = row
        first_text = datetime.fromtimestamp(first / 1000, timezone.utc).isoformat() if first else "-"
        last_text = datetime.fromtimestamp(last / 1000, timezone.utc).isoformat() if last else "-"
        timestamps = [item[0] for item in db.execute(
            "SELECT ts_ms FROM candles WHERE inst_id=? AND timeframe=? ORDER BY ts_ms",
            (inst_id, TIMEFRAME),
        )]
        missing = sum(max(0, (right - left) // INTERVAL_MS - 1)
                      for left, right in zip(timestamps, timestamps[1:]))
        lag_min = round((time.time() * 1000 - last - INTERVAL_MS) / 60000, 1) if last else None
        print(f"{inst_id}: {count} candles; first={first_text}; last={last_text}; "
              f"missing_intervals={missing}; lag_minutes={lag_min}")



def health_status(path: Path = DB_PATH, max_lag_minutes: float = 45.0) -> tuple[bool, str]:
    if not path.is_file():
        return False, "market database missing"
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        stale = []
        for inst_id in PAIR_MAP:
            row = db.execute("SELECT MAX(ts_ms) FROM candles WHERE inst_id=? AND timeframe=?",
                             (inst_id, TIMEFRAME)).fetchone()
            last = row[0] if row else None
            if last is None:
                stale.append(f"{inst_id}: no candles")
                continue
            lag = (time.time() * 1000 - last - INTERVAL_MS) / 60000
            if lag > max_lag_minutes:
                stale.append(f"{inst_id}: {lag:.1f} minutes behind")
        return (False, "; ".join(stale)) if stale else (True, "both pairs current")
    finally:
        db.close()
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="REST backfill once, then exit")
    parser.add_argument("--status", action="store_true", help="show stored candle counts without network")
    parser.add_argument("--healthcheck", action="store_true", help="exit nonzero when candles are stale")
    parser.add_argument("--initial-days", type=int, default=3)
    parser.add_argument("--proxy", default=os.environ.get("OKX_PROXY_URL") or None)
    args = parser.parse_args()
    if args.initial_days < 1 or args.initial_days > 90:
        parser.error("--initial-days must be between 1 and 90")
    if args.healthcheck:
        ok, message = health_status()
        print(message)
        return 0 if ok else 1
    setup_logging()
    db = connect_db()
    try:
        if args.status:
            status(db)
            return 0
        if args.once:
            backfill(db, args.proxy, args.initial_days, force_initial=True)
            status(db)
            return 0
        while True:
            try:
                backfill(db, args.proxy, args.initial_days)
                stream(db, args.proxy)
            except KeyboardInterrupt:
                return 0
            except Exception as exc:
                LOG.warning("Recorder disconnected: %s; retry in 10 seconds", exc)
                time.sleep(10)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())






