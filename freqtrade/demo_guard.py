"""Guarded OKX Demo startup. Never falls back to real-market orders."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "user_data" / "config_okx_demo.json"
PROXY_CONFIG = ROOT / "user_data" / "config_proxy_local.example.json"
STRATEGY = "OKXDemoFuturesStrategy"


def check_config() -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    exchange = config.get("exchange", {})
    ccxt_config = exchange.get("ccxt_config", {})
    headers = {str(k).lower(): str(v) for k, v in ccxt_config.get("headers", {}).items()}
    options = ccxt_config.get("options", {})
    urls = ccxt_config.get("urls", {}).get("api", {})
    checks = {
        "exchange is okx": exchange.get("name") == "okx",
        "demo orders enabled": config.get("dry_run") is False,
        "futures isolated margin": config.get("trading_mode") == "futures" and config.get("margin_mode") == "isolated",
        "demo request header": headers.get("x-simulated-trading") == "1",
        "REST host": ccxt_config.get("hostname") == "openapi.okx.com" and urls.get("rest") == "https://openapi.okx.com",
        "Demo WebSocket host": urls.get("ws") == "wss://wspap.okx.com:8443/ws/v5",
        "CCXT sandbox flag": options.get("sandboxMode") is True,
        "API server disabled": config.get("api_server", {}).get("enabled") is False,
        "limited pairs": 0 < len(exchange.get("pair_whitelist", [])) <= 2,
        "no alternate CCXT overrides": not exchange.get("ccxt_sync_config") and not exchange.get("ccxt_async_config"),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError("Unsafe OKX Demo configuration: " + ", ".join(failed))
    allowed_env = {"FREQTRADE__EXCHANGE__API_KEY", "FREQTRADE__EXCHANGE__SECRET", "FREQTRADE__EXCHANGE__PASSWORD"}
    overrides = [key for key in os.environ if key.startswith("FREQTRADE__") and key not in allowed_env]
    if overrides:
        raise RuntimeError("Unexpected Freqtrade environment overrides: " + ", ".join(overrides))
    check_ccxt_wiring(ccxt_config)
    print("OKX Demo configuration checks passed.")
    return config



def check_ccxt_wiring(ccxt_config: dict) -> None:
    """Check effective REST header and all three Demo WS URLs without network."""
    import asyncio
    import ccxt
    import ccxt.pro

    probe = {**ccxt_config, "apiKey": "probe", "secret": "probe", "password": "probe"}
    rest = ccxt.okx(probe)
    try:
        signed = rest.sign("account/balance", "private", "GET")
        headers = rest.prepare_request_headers(signed["headers"])
        if not signed["url"].startswith("https://openapi.okx.com/api/v5/"):
            raise RuntimeError("REST private request did not use openapi.okx.com")
        if headers.get("x-simulated-trading") != "1":
            raise RuntimeError("REST private request lacks the OKX Demo header")
    finally:
        rest.close()
    ws = ccxt.pro.okx(ccxt_config)
    try:
        for channel, access, path in (("tickers", "public", "/public"),
                                      ("orders", "private", "/private"),
                                      ("candle15m", "public", "/business")):
            url = ws.get_url(channel, access)
            if not url.startswith("wss://wspap.okx.com:8443/ws/v5" + path):
                raise RuntimeError("WebSocket request did not use OKX Demo: " + path)
    finally:
        asyncio.run(ws.close())
def check_proxy_config() -> str:
    overlay = json.loads(PROXY_CONFIG.read_text(encoding="utf-8-sig"))
    settings = overlay.get("exchange", {}).get("ccxt_config", {})
    if set(overlay) != {"exchange"} or set(overlay["exchange"]) != {"ccxt_config"}:
        raise RuntimeError("Proxy overlay may only contain exchange.ccxt_config")
    if set(settings) != {"httpsProxy", "wssProxy"}:
        raise RuntimeError("Proxy overlay may only contain httpsProxy and wssProxy")
    proxy = settings["httpsProxy"]
    if proxy != settings["wssProxy"] or not proxy.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("Proxy overlay must use the same local HTTP proxy for REST and WS")
    print("Local proxy configured for REST and WS:", proxy)
    return proxy


def check_demo_credentials(config: dict, proxy: str | None = None) -> None:
    names = ("API_KEY", "SECRET", "PASSWORD")
    values = {name: os.environ.get("FREQTRADE__EXCHANGE__" + name, "").strip() for name in names}
    if not all(values.values()):
        raise RuntimeError("Demo API_KEY, SECRET and PASSWORD are required in .env.demo")

    import ccxt

    settings = {
        "apiKey": values["API_KEY"],
        "secret": values["SECRET"],
        "password": values["PASSWORD"],
        "options": {"defaultType": "swap", "sandboxMode": True},
        "hostname": "openapi.okx.com",
        "urls": {"api": {"rest": "https://openapi.okx.com"}},
        "headers": {"x-simulated-trading": "1"},
        "enableRateLimit": True,
    }
    if proxy:
        settings["httpsProxy"] = proxy
    exchange = ccxt.okx(settings)
    try:
        exchange.set_sandbox_mode(True)
        if exchange.headers.get("x-simulated-trading") != "1":
            raise RuntimeError("CCXT demo header was not set")
        # Signed read-only request. A real-market key should fail here.
        balance = exchange.fetch_balance()
        if not isinstance(balance, dict):
            raise RuntimeError("Unexpected OKX Demo balance response")
    finally:
        exchange.close()
    print("Authenticated signed OKX Demo balance request passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true", help="offline static checks only")
    parser.add_argument("--preflight", action="store_true", help="signed read-only Demo API check")
    parser.add_argument("--local-proxy", action="store_true", help="use optional localhost proxy overlay")
    args = parser.parse_args()
    try:
        config = check_config()
        proxy = check_proxy_config() if args.local_proxy else None
        if args.check_config:
            return 0
        check_demo_credentials(config, proxy)
        if args.preflight:
            return 0
        db = (ROOT / "user_data" / "tradesv3-demo.sqlite").as_posix()
        logfile = str(ROOT / "user_data" / "logs" / "freqtrade-demo.log")
        command = [sys.executable, "-m", "freqtrade", "trade", "--config", str(CONFIG)]
        if proxy:
            command += ["--config", str(PROXY_CONFIG)]
        command += ["--strategy", STRATEGY, "--db-url", "sqlite:///" + db, "--logfile", logfile]
        print("Starting Freqtrade on authenticated OKX Demo API only.", flush=True)
        return subprocess.call(command, cwd=str(ROOT))
    except Exception as exc:
        print("Demo startup blocked: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

