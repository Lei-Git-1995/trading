"""OKX demo futures: long-only "consolidation then volume breakout" strategy.

Entry idea: a pair has been ranging sideways for a while (tight, low-volatility
range), then price breaks above the recent range high on a clear volume spike.
Long only (can_short = False).
"""
from freqtrade.strategy import IStrategy
import talib.abstract as ta


class OKXDemoBreakoutStrategy(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "15m"
    startup_candle_count = 220
    process_only_new_candles = True
    position_adjustment_enable = False
    use_exit_signal = True

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 2},
        {"method": "StoplossGuard", "lookback_period_candles": 96,
         "trade_limit": 3, "stop_duration_candles": 12, "only_per_pair": True},
        {"method": "MaxDrawdown", "lookback_period_candles": 192,
         "trade_limit": 6, "stop_duration_candles": 48,
         "max_allowed_drawdown": 0.15, "calculation_mode": "equity"},
    ]
    stoploss = -0.10
    minimal_roi = {"0": 0.12, "60": 0.06, "180": 0.03, "420": 0}

    def populate_indicators(self, dataframe, metadata):
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volume_mean"]

        lookback = 30
        dataframe["range_high"] = dataframe["high"].rolling(lookback).max().shift(1)
        dataframe["range_low"] = dataframe["low"].rolling(lookback).min().shift(1)
        dataframe["range_width"] = (
            (dataframe["range_high"] - dataframe["range_low"]) / dataframe["close"]
        )

        tight = (dataframe["range_width"] < 0.10).astype(int)
        dataframe["tight_count"] = tight.rolling(20).sum()
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        consolidation = dataframe["tight_count"] >= 12
        breakout = dataframe["close"] > dataframe["range_high"]
        volume_surge = dataframe["vol_ratio"] >= 2.0
        green = dataframe["close"] > dataframe["open"]
        uptrend = dataframe["close"] > dataframe["ema_slow"]

        entry = (
            consolidation
            & breakout
            & volume_surge
            & green
            & uptrend
            & (dataframe["volume"] > 0)
        )
        strong = entry & (dataframe["vol_ratio"] >= 3.0) & (dataframe["adx"] >= 25)

        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (1, "breakout_3x")
        dataframe.loc[strong, ["enter_long", "enter_tag"]] = (1, "breakout_5x")
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        exit_signal = (
            (dataframe["close"] < dataframe["ema_fast"])
            | (dataframe["rsi"] > 78)
        ) & (dataframe["volume"] > 0)
        dataframe.loc[exit_signal, ["exit_long", "exit_tag"]] = (1, "momentum_exit")
        return dataframe

    def leverage(
        self, pair, current_time, current_rate, proposed_leverage,
        max_leverage, entry_tag, side, **kwargs
    ) -> float:
        target = 5.0 if entry_tag == "breakout_5x" else 3.0
        return max(1.0, min(target, float(max_leverage)))
