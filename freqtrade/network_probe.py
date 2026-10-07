"""Read-only OKX Demo REST and public WebSocket connectivity checks."""
from __future__ import annotations

import argparse
import asyncio
import json
import os

import requests
from websockets.sync.client import connect

REST = "https://openapi.okx.com/api/v5/public/time"
WS = "wss://wspap.okx.com:8443/ws/v5/public"


def check_rest(proxy: str | None) -> None:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = requests.get(REST, proxies=proxies, timeout=12)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != "0":
        raise RuntimeError(f"OKX REST returned code {data.get('code')}")
    print("REST OK: server time", data["data"][0]["ts"])


def check_ws(proxy: str | None) -> None:
    with connect(WS, proxy=proxy, open_timeout=12, close_timeout=3) as ws:
        ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]}))
        for _ in range(5):
            message = json.loads(ws.recv(timeout=12))
            if message.get("event") == "error":
                raise RuntimeError(f"OKX WS error: {message}")
            if message.get("arg", {}).get("channel") == "tickers" and message.get("data"):
                print("WS OK: BTC-USDT-SWAP last", message["data"][0].get("last"))
                return
    raise RuntimeError("No BTC ticker received from OKX Demo WS")



def check_ws_candles(proxy: str | None) -> None:
    url = "wss://wspap.okx.com:8443/ws/v5/business"
    with connect(url, proxy=proxy, open_timeout=12, close_timeout=3) as ws:
        ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "candle15m", "instId": "BTC-USDT-SWAP"}]}))
        for _ in range(5):
            message = json.loads(ws.recv(timeout=12))
            if message.get("event") == "error":
                raise RuntimeError(f"OKX business WS error: {message}")
            if message.get("arg", {}).get("channel") == "candle15m" and message.get("data"):
                candle = message["data"][0]
                print("Business WS OK: BTC 15m candle", candle[0], candle[4], "confirm", candle[-1])
                return
    raise RuntimeError("No BTC candle received from OKX Demo business WS")
async def check_ccxt_pro(proxy: str | None) -> None:
    import ccxt.pro

    config = {
        "hostname": "openapi.okx.com",
        "urls": {"api": {"rest": "https://openapi.okx.com", "ws": "wss://wspap.okx.com:8443/ws/v5"}},
        "options": {"defaultType": "swap", "sandboxMode": True},
        "headers": {"x-simulated-trading": "1"},
    }
    if proxy:
        config.update({"httpsProxy": proxy, "wssProxy": proxy})
    exchange = ccxt.pro.okx(config)
    try:
        await asyncio.wait_for(exchange.load_markets(), timeout=25)
        ticker = await asyncio.wait_for(exchange.watch_ticker("BTC/USDT:USDT"), timeout=25)
        print("CCXT Pro OK: BTC/USDT:USDT last", ticker.get("last"))
    finally:
        await exchange.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy", default=os.environ.get("OKX_PROXY_URL") or None, help="Optional local HTTP proxy URL, e.g. http://127.0.0.1:7897")
    parser.add_argument("--ccxt-pro", action="store_true", help="also validate the CCXT Pro feed used by Freqtrade")
    args = parser.parse_args()
    check_rest(args.proxy)
    check_ws(args.proxy)
    check_ws_candles(args.proxy)
    if args.ccxt_pro:
        asyncio.run(check_ccxt_pro(args.proxy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



