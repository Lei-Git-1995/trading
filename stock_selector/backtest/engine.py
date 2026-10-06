"""Rolling historical evaluation for stock_selector strategies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    metrics: dict


def _equity_metrics(returns: pd.Series) -> tuple[float, float]:
    if returns.empty:
        return 0.0, 0.0
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    return float(equity.iloc[-1] - 1), float(drawdown.min())


def evaluate_rolling(
    history: pd.DataFrame,
    strategy_id: str,
    holding_days: int = 1,
    fee_rate: float = 0.0,
    signal_func: Optional[Callable] = None,
) -> BacktestResult:
    """Evaluate signals at each close and enter at the next day's open.

    ``history`` must use the project's normalized Chinese OHLC column names.
    Signals are evaluated only on data up to that signal date. Trades overlap
    when holding_days > 1; portfolio drawdown compounds the trade sequence.
    """
    from stock_selector.strategies.technical_selection import TechnicalSelector

    if holding_days < 1:
        raise ValueError('holding_days must be >= 1')
    if fee_rate < 0:
        raise ValueError('fee_rate must be >= 0')
    # TechnicalSelector's indicator pipeline requires complete daily OHLCV bars.
    required = ['开盘', '收盘', '最高', '最低', '成交量']
    missing = [col for col in required if col not in history]
    if missing:
        raise ValueError('missing OHLC columns: %s' % ', '.join(missing))
    data = history.copy()
    if '日期' in data:
        data['日期'] = pd.to_datetime(data['日期'], errors='coerce')
        data = data.sort_values('日期').reset_index(drop=True)
    else:
        data = data.reset_index(drop=True)
    signal_func = signal_func or (lambda frame: TechnicalSelector.evaluate(frame, strategy_id)['matched'])
    rows = []
    # Need entry row after signal and an exit close holding_days sessions later.
    for signal_i in range(0, len(data) - holding_days):
        signal = signal_func(data.iloc[:signal_i + 1].copy())
        matched = signal.get('matched', False) if isinstance(signal, dict) else bool(signal)
        if not matched:
            continue
        entry_i, exit_i = signal_i + 1, signal_i + holding_days
        entry = float(data.iloc[entry_i]['开盘'])
        exit_price = float(data.iloc[exit_i]['收盘'])
        if entry <= 0:
            continue
        ret = exit_price / entry - 1 - 2 * fee_rate
        rows.append({
            'signal_date': data.iloc[signal_i].get('日期', signal_i),
            'entry_date': data.iloc[entry_i].get('日期', entry_i),
            'exit_date': data.iloc[exit_i].get('日期', exit_i),
            'entry_price': entry, 'exit_price': exit_price, 'return': ret,
        })
    trades = pd.DataFrame(rows, columns=['signal_date', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 'return'])
    returns = trades['return'] if not trades.empty else pd.Series(dtype=float)
    cumulative, max_drawdown = _equity_metrics(returns)
    gains = returns[returns > 0].sum() if len(returns) else 0.0
    losses = -returns[returns < 0].sum() if len(returns) else 0.0
    metrics = {
        'trade_count': int(len(trades)),
        'win_rate': float((returns > 0).mean()) if len(returns) else 0.0,
        'average_return': float(returns.mean()) if len(returns) else 0.0,
        'cumulative_return': cumulative,
        'max_drawdown': max_drawdown,
        'profit_factor': float(gains / losses) if losses else (float('inf') if gains else 0.0),
    }
    return BacktestResult(trades=trades, metrics=metrics)
