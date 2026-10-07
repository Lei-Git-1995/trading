"""Offline persistence checks for the OKX candle recorder."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from market_recorder import INTERVAL_MS, backfill_start, connect_db, process_ws_message, save_candle


class MarketRecorderTests(unittest.TestCase):
    def test_closed_ws_candle_is_saved_once(self):
        with tempfile.TemporaryDirectory() as temp:
            db = connect_db(Path(temp) / "candles.sqlite")
            try:
                ts = ((int(time.time() * 1000) // INTERVAL_MS) - 2) * INTERVAL_MS
                candle = [str(ts), "100", "102", "99", "101", "1000", "0", "0", "1"]
                message = {"arg": {"channel": "candle15m", "instId": "BTC-USDT-SWAP"}, "data": [candle]}
                self.assertEqual(process_ws_message(db, message), 1)
                self.assertEqual(process_ws_message(db, message), 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM candles").fetchone()[0], 1)
                candle[-1] = "0"
                self.assertEqual(process_ws_message(db, message), 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM candles").fetchone()[0], 1)
            finally:
                db.close()

    def test_reconnect_rechecks_one_day_without_refetching_full_history(self):
        end_ms = 100 * 86_400_000
        last_ms = end_ms - INTERVAL_MS
        self.assertEqual(backfill_start(last_ms, end_ms, 7, False), last_ms - 86_400_000)
        self.assertEqual(backfill_start(last_ms, end_ms, 7, True), end_ms - 7 * 86_400_000)

    def test_current_rest_candle_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            db = connect_db(Path(temp) / "candles.sqlite")
            try:
                current = (int(time.time() * 1000) // INTERVAL_MS) * INTERVAL_MS
                self.assertFalse(save_candle(db, "ETH-USDT-SWAP", [current, 100, 101, 99, 100, 5], "REST"))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM candles").fetchone()[0], 0)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()

