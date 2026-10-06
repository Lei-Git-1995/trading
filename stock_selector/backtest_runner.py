"""Run a historical technical strategy backtest on local normalized CSV data."""
import argparse
import pandas as pd

from stock_selector.backtest import evaluate_rolling
from stock_selector.backtest.report import write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='CSV containing normalized daily OHLC history')
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--holding-days', type=int, default=1)
    parser.add_argument('--fee-rate', type=float, default=0.0, help='one-way fee as decimal, e.g. 0.001')
    parser.add_argument('--output', default='output/backtest.md')
    args = parser.parse_args(argv)
    frame = pd.read_csv(args.input)
    result = evaluate_rolling(frame, args.strategy, args.holding_days, args.fee_rate)
    path = write_report(result, args.output)
    print('Trades: %d | Win rate: %.2f%% | Average: %.2f%% | Max DD: %.2f%%' % (
        result.metrics['trade_count'], result.metrics['win_rate'] * 100,
        result.metrics['average_return'] * 100, result.metrics['max_drawdown'] * 100))
    print('Report: %s' % path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
