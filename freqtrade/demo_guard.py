"""受保护的 OKX 模拟盘启动脚本。绝不回退到实盘下单。"""
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
STRATEGY = "OKXDemoBreakoutStrategy"
MAX_PAIRS = 30


def valid_pair_list(pairs: list) -> bool:
    """At most MAX_PAIRS pairs, all USDT-settled linear-swap symbols."""
    if not (0 < len(pairs) <= MAX_PAIRS):
        return False
    return all(
        isinstance(pair, str) and pair.endswith("/USDT:USDT") and pair.count("/") == 1
        for pair in pairs
    )


def uses_dynamic_pairlist(config: dict) -> bool:
    """True when the first pairlist generator selects pairs dynamically from the exchange."""
    pairlists = config.get("pairlists", [])
    return (
        bool(pairlists)
        and isinstance(pairlists[0], dict)
        and pairlists[0].get("method") == "VolumePairList"
    )


def dynamic_pairlist_ok(config: dict) -> bool:
    """A dynamic VolumePairList may omit the static whitelist, but must stay within MAX_PAIRS."""
    pairlists = config.get("pairlists", [])
    if not pairlists or not isinstance(pairlists[0], dict):
        return False
    try:
        number_assets = int(pairlists[0].get("number_assets", 0))
    except (TypeError, ValueError):
        return False
    return 0 < number_assets <= MAX_PAIRS


def api_server_is_local(api_server: dict) -> bool:
    """Allow FreqUI only on loopback, and only with real credentials."""
    if not api_server.get("enabled"):
        return True
    if api_server.get("listen_ip_address") not in ("127.0.0.1", "localhost", "::1"):
        return False
    for key in ("password", "jwt_secret_key", "ws_token"):
        value = api_server.get(key) or ""
        if not value or value.startswith("CHANGE_THIS"):
            return False
    return True


def check_config(config_path: Path = CONFIG) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    exchange = config.get("exchange", {})
    ccxt_config = exchange.get("ccxt_config", {})
    headers = {str(k).lower(): str(v) for k, v in ccxt_config.get("headers", {}).items()}
    options = ccxt_config.get("options", {})
    urls = ccxt_config.get("urls", {}).get("api", {})
    pair_whitelist = exchange.get("pair_whitelist") or []
    if uses_dynamic_pairlist(config):
        pair_list_ok = dynamic_pairlist_ok(config) and (
            not pair_whitelist or valid_pair_list(pair_whitelist)
        )
    else:
        pair_list_ok = valid_pair_list(pair_whitelist)
    checks = {
        "exchange is okx": exchange.get("name") == "okx",
        "demo orders enabled": config.get("dry_run") is False,
        "futures isolated margin": config.get("trading_mode") == "futures" and config.get("margin_mode") == "isolated",
        "demo request header": headers.get("x-simulated-trading") == "1",
        "REST host": ccxt_config.get("hostname") == "openapi.okx.com" and urls.get("rest") == "https://openapi.okx.com",
        "Demo WebSocket host": urls.get("ws") == "wss://wspap.okx.com:8443/ws/v5",
        "CCXT sandbox flag": options.get("sandboxMode") is True,
        "API server localhost-only": api_server_is_local(config.get("api_server", {})),
        "valid pair list": pair_list_ok,
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
    print("OKX 模拟盘配置检查通过。")
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
    print("本地代理已配置（REST 与 WS）：", proxy)
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
    print("OKX 模拟盘签名认证余额查询通过。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true", help="仅做离线静态配置检查")
    parser.add_argument("--preflight", action="store_true", help="签名只读的模拟盘 API 预检")
    parser.add_argument("--local-proxy", action="store_true", help="使用可选的本地代理覆盖配置")
    parser.add_argument("--config", default=str(CONFIG), help="配置文件路径（默认：主模拟盘配置）")
    parser.add_argument("--strategy", default=STRATEGY, help="策略类名")
    parser.add_argument("--db", default="tradesv3-demo.sqlite", help="user_data 内的 sqlite 文件名")
    parser.add_argument("--logfile", default="freqtrade-demo.log", help="user_data/logs 内的日志文件名")
    args = parser.parse_args()
    config_path = Path(args.config)
    try:
        config = check_config(config_path)
        proxy = check_proxy_config() if args.local_proxy else None
        if args.check_config:
            return 0
        check_demo_credentials(config, proxy)
        if args.preflight:
            return 0
        db = (ROOT / "user_data" / args.db).as_posix()
        logfile = str(ROOT / "user_data" / "logs" / args.logfile)
        command = [sys.executable, "-m", "freqtrade", "trade", "--config", str(config_path)]
        if proxy:
            command += ["--config", str(PROXY_CONFIG)]
        command += ["--strategy", args.strategy, "--db-url", "sqlite:///" + db, "--logfile", logfile]
        print("仅通过已认证的 OKX 模拟盘 API 启动 Freqtrade。", flush=True)
        return subprocess.call(command, cwd=str(ROOT))
    except Exception as exc:
        print("模拟盘启动被阻止：" + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

