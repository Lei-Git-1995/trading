"""Read-only weekly summary of Freqtrade OKX Demo trades."""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "user_data" / "tradesv3-demo.sqlite"


def summarize(db_path: Path, days: int, starting_equity: float = 0.0) -> str:
    if days < 1:
        raise ValueError("days must be at least 1")
    if not db_path.is_file():
        raise FileNotFoundError(f"Demo trade database not found: {db_path}")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(trades)")}
        needed = {"pair", "enter_tag", "leverage", "close_profit", "close_profit_abs", "close_date", "is_open"}
        if not needed.issubset(columns):
            raise RuntimeError("Trade table is missing expected Freqtrade columns")
        rows = db.execute(
            "SELECT pair, enter_tag, leverage, close_profit, close_profit_abs, close_date "
            "FROM trades WHERE is_open = 0 AND close_date >= ? ORDER BY close_date, id",
            (since,),
        ).fetchall()
        open_count = db.execute("SELECT COUNT(*) FROM trades WHERE is_open = 1").fetchone()[0]

    groups = defaultdict(list)
    for pair, tag, leverage, profit_ratio, profit_abs, close_date in rows:
        groups[tag or f"{leverage or 1:g}x_unknown"].append(
            (float(profit_ratio or 0), float(profit_abs or 0), pair, close_date)
        )
    lines = [
        "# OKX 模拟盘交易复盘", "",
        f"统计时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"窗口：最近 {days} 天；已平仓 {len(rows)} 笔，当前未平仓 {open_count} 笔", "",
        "| 信号组 | 笔数 | 胜率 | 平均收益率 | 净收益 USDT |",
        "|---|---:|---:|---:|---:|",
    ]
    for tag, trades in sorted(groups.items()):
        count = len(trades)
        wins = sum(item[1] > 0 for item in trades)
        avg_ratio = sum(item[0] for item in trades) / count
        net = sum(item[1] for item in trades)
        lines.append(f"| {tag} | {count} | {wins/count:.1%} | {avg_ratio:.2%} | {net:.2f} |")
    if not rows:
        lines.append("| 暂无平仓交易 | 0 | — | — | 0.00 |")
    pnl = 0.0
    peak = starting_equity if starting_equity > 0 else 0.0
    max_drawdown = 0.0
    for row in rows:
        pnl += float(row[4] or 0)
        equity = starting_equity + pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    lines += ["", f"合计净收益：{pnl:.2f} USDT", f"交易序列最大回撤：{max_drawdown:.2f} USDT"]
    if starting_equity > 0 and peak > 0:
        lines.append(f"以输入初始权益估算的最大回撤：{max_drawdown / peak:.2%}")
    lines += ["", "该报告按已平仓交易计算，不包含未平仓浮盈亏。请与 OKX 模拟盘的订单、资金费率和账户权益核对。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--starting-equity", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize(args.db, args.days, args.starting_equity)
    output = args.output or ROOT / "user_data" / "reports" / f"demo_review_{datetime.now():%Y-%m-%d}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
