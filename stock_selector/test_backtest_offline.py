"""Offline checks for rolling backtest timing and report output."""
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from stock_selector.backtest import evaluate_rolling
from stock_selector.backtest.report import write_report


class BacktestOfflineTests(unittest.TestCase):
    def test_signal_enters_next_open_and_exits_after_holding_period(self):
        history = pd.DataFrame({
            '日期': pd.date_range('2026-01-01', periods=5),
            '开盘': [10, 11, 12, 13, 14],
            '收盘': [10.5, 11.5, 13, 12, 15],
            '最高': [11, 12, 13, 14, 16],
            '最低': [9, 10, 11, 12, 13],
            '成交量': [100] * 5,
        })
        signal = lambda frame: len(frame) == 2
        result = evaluate_rolling(history, 'unused', holding_days=2, signal_func=signal)
        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(trade.entry_price, 12)
        self.assertEqual(trade.exit_price, 12)
        self.assertEqual(result.metrics['trade_count'], 1)

    def test_csv_report_is_written(self):
        history = pd.DataFrame({
            '开盘': [10, 10], '收盘': [10, 11],
            '最高': [11, 12], '最低': [9, 10], '成交量': [100, 120],
        })
        result = evaluate_rolling(history, 'unused', signal_func=lambda frame: len(frame) == 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_report(result, Path(temp_dir) / 'trades.csv')
            self.assertTrue(path.exists())
            self.assertIn('return', path.read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
