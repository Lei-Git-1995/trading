"""Build a deployment ZIP from an explicit allowlist without credentials or runtime data."""
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
    "systemd/okx-market-recorder.service", "systemd/freqtrade-okx-demo.service",
    "systemd/okx-freqtrade-backup.service", "systemd/okx-freqtrade-backup.timer",
)
USER_CONFIGS = {
    "config.json", "config_okx_demo.json", "config_okx_futures_backtest.json",
    "config_proxy_local.example.json",
}


def sanitized_config(path: Path) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    sensitive = {
        "exchange": ("api_key", "key", "secret", "password", "private_key"),
        "telegram": ("token", "chat_id"),
        "api_server": ("password", "jwt_secret_key", "ws_token"),
    }
    for section, fields in sensitive.items():
        values = data.get(section, {})
        if isinstance(values, dict):
            for field in fields:
                if field in values:
                    values[field] = ""
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def allowed_user_file(path: Path) -> bool:
    if not path.is_file():
        return False
    relative = path.relative_to(ROOT / "user_data")
    parts = relative.parts
    if len(parts) == 1:
        return parts[0] in USER_CONFIGS
    if parts[0] == "strategies" and path.suffix == ".py" and "__pycache__" not in parts:
        return True
    if len(parts) >= 3 and parts[:2] == ("data", "okx"):
        return path.suffix in {".feather", ".parquet"} or (
            path.name.startswith("leverage_tiers_") and path.suffix == ".json"
        )
    return False


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
                if path.name in USER_CONFIGS:
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
    print("Package contains allowlisted code/config and public history only; private .env.demo excluded.")

