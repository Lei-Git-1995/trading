"""Backtest report serialization."""
import json
from pathlib import Path


def write_report(result, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == '.csv':
        result.trades.to_csv(output, index=False, encoding='utf-8-sig')
        return output
    m = result.metrics
    lines = [
        '# Strategy backtest', '',
        '| Metric | Value |', '|---|---:|',
        '| Trades | %d |' % m['trade_count'],
        '| Win rate | %.2f%% |' % (m['win_rate'] * 100),
        '| Average return | %.2f%% |' % (m['average_return'] * 100),
        '| Cumulative return | %.2f%% |' % (m['cumulative_return'] * 100),
        '| Max drawdown | %.2f%% |' % (m['max_drawdown'] * 100), '',
        '| Profit factor | %s |' % ('∞' if m.get('profit_factor') == float('inf') else '%.2f' % m.get('profit_factor', 0.0)), '',
        '## Trades', '',
    ]
    if result.trades.empty:
        lines.append('No trades.')
    else:
        lines.extend(['| Signal date | Entry date | Exit date | Entry | Exit | Return |', '|---|---|---|---:|---:|---:|'])
        for _, row in result.trades.iterrows():
            lines.append('| %s | %s | %s | %.4f | %.4f | %.2f%% |' % (
                row.signal_date, row.entry_date, row.exit_date, row.entry_price,
                row.exit_price, row['return'] * 100))
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return output
