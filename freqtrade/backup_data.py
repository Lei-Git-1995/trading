"""Consistent daily backups of OKX Demo SQLite data and small configuration files."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_NAMES = ("tradesv3-demo.sqlite", "market_data.sqlite")
STATIC_FILES = (
    "docker-compose.demo.yml", "docker-compose.recorder.yml",
    "demo_guard.py", "market_recorder.py", "network_probe.py",
    "demo_report.py", "backup_data.py", "package_transfer.py",
    "README_OKX模拟盘合约.md", "README_Linux部署与数据记录.md",
    "user_data/config_okx_demo.json", "user_data/config_okx_futures_backtest.json",
    "user_data/strategies/OKXDemoFuturesStrategy.py",
)


def backup_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    read_db = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        write_db = sqlite3.connect(target)
        try:
            read_db.backup(write_db)
        finally:
            write_db.close()
    finally:
        read_db.close()


def copy_static(source: Path, target: Path, relative: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if relative.startswith("user_data/config") and relative.endswith(".json"):
        from package_transfer import sanitized_config
        target.write_bytes(sanitized_config(source))
    else:
        shutil.copy2(source, target)


def create_backup(output_dir: Path, keep_days: int) -> Path:
    if keep_days < 1:
        raise ValueError("keep_days must be at least 1")
    output_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        output_dir.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = output_dir / f"okx-demo-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="backup-stage-", dir=output_dir) as temp:
        stage = Path(temp)
        for name in DB_NAMES:
            source = ROOT / "user_data" / name
            if source.is_file():
                backup_sqlite(source, stage / "user_data" / name)
        for relative in STATIC_FILES:
            source = ROOT / relative
            if source.is_file():
                copy_static(source, stage / relative, relative)
        logs = ROOT / "user_data" / "logs"
        if logs.is_dir():
            for source in logs.glob("*.log"):
                if source.is_file():
                    target = stage / "user_data" / "logs" / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        with tarfile.open(archive, "w:gz") as tar:
            for source in stage.rglob("*"):
                if source.is_file():
                    tar.add(source, arcname=source.relative_to(stage).as_posix())
    if os.name != "nt":
        archive.chmod(0o600)
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    for old in output_dir.glob("okx-demo-*.tar.gz"):
        if old != archive and datetime.fromtimestamp(old.stat().st_mtime, timezone.utc) < cutoff:
            old.unlink()
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backups")
    parser.add_argument("--keep-days", type=int, default=30)
    args = parser.parse_args()
    archive = create_backup(args.output_dir, args.keep_days)
    print(f"Backup: {archive} ({archive.stat().st_size} bytes)")
    print(".env.demo excluded and config API fields redacted; review logs before sharing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

