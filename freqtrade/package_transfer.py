"""Build a deployment ZIP without credentials, runtime databases, or logs."""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "freqtrade-transfer.zip"
ROOT_FILES = (
    ".gitignore", ".env.demo.example", "docker-compose.yml", "docker-compose.demo.yml",
    "docker-compose.recorder.yml", "demo_guard.py", "market_recorder.py",
    "network_probe.py", "demo_report.py", "backup_data.py", "package_transfer.py",
    "README_安装启动使用.md", "README_OKX模拟盘合约.md",
    "README_Linux部署与数据记录.md",
)
EXCLUDED_DIRS = {"__pycache__", "logs", "reports", "backtest_results", "hyperopt_results", "notebooks", "freqaimodels", "hyperopts", "plot"}
EXCLUDED_SUFFIXES = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".pyc", ".pkl")


def sanitized_config(path: Path) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    exchange = data.get("exchange", {})
    for field in ("api_key", "key", "secret", "password"):
        if field in exchange:
            exchange[field] = ""
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def allowed_user_file(path: Path) -> bool:
    relative = path.relative_to(ROOT / "user_data")
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.name.startswith(".env") or path.name.endswith(EXCLUDED_SUFFIXES):
        return False
    return path.is_file()


def build() -> Path:
    with tempfile.NamedTemporaryFile(prefix="transfer-", suffix=".zip", dir=ROOT, delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for relative in ROOT_FILES:
                path = ROOT / relative
                if path.is_file():
                    archive.write(path, relative)
            for path in (ROOT / "user_data").rglob("*"):
                if not allowed_user_file(path):
                    continue
                relative = path.relative_to(ROOT).as_posix()
                if path.suffix.lower() == ".json" and path.name.startswith("config"):
                    archive.writestr(relative, sanitized_config(path))
                else:
                    archive.write(path, relative)
        os.replace(temp_path, OUTPUT)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return OUTPUT


if __name__ == "__main__":
    output = build()
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
    print(f"{output} ({output.stat().st_size} bytes; {len(names)} files)")
    print("Runtime SQLite, logs, backups, virtualenv and private .env.demo excluded.")

