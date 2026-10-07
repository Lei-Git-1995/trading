"""OKX demo futures strategy: long-only, 3x base / 5x strong entries."""
from freqtrade.strategy import IStrategy
import talib.abstract as ta


class OKXDemoFuturesStrategy(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "15m"
    startup_candle_count = 100
    process_only_new_candles = True
    position_adjustment_enable = False
    use_exit_signal = True

    # Freqtrade interprets stoploss/ROI as leveraged trade profit ratios.
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 2},
        {"method": "StoplossGuard", "lookback_period_candles": 96,
         "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": False},
        {"method": "MaxDrawdown", "lookback_period_candles": 192,
         "trade_limit": 4, "stop_duration_candles": 96,
         "max_allowed_drawdown": 0.10, "calculation_mode": "equity"},
    ]
    stoploss = -0.06
    minimal_roi = {"0": 0.08, "60": 0.04, "180": 0.02, "360": 0}

    def populate_indicators(self, dataframe, metadata):
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["close"]
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        base = (
            (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
            & (dataframe["rsi"] > 50)
            & (dataframe["rsi"] < 70)
            & (dataframe["volume"] > 0)
        )
        strong = (
            base
            & (dataframe["rsi"] >= 55)
            & (dataframe["rsi"] <= 65)
            & (dataframe["adx"] >= 25)
            & (dataframe["volume"] >= 1.3 * dataframe["volume_mean"])
            & (dataframe["atr_ratio"] <= 0.008)
        )
        dataframe.loc[base, ["enter_long", "enter_tag"]] = (1, "base_3x")
        dataframe.loc[strong, ["enter_long", "enter_tag"]] = (1, "strong_5x")
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        exit_signal = (
            (dataframe["ema_fast"] < dataframe["ema_slow"])
            | (dataframe["rsi"] < 45)
        ) & (dataframe["volume"] > 0)
        dataframe.loc[exit_signal, ["exit_long", "exit_tag"]] = (1, "trend_or_rsi_exit")
        return dataframe

    def leverage(
        self, pair, current_time, current_rate, proposed_leverage,
        max_leverage, entry_tag, side, **kwargs
    ) -> float:
        target = 5.0 if entry_tag == "strong_5x" else 3.0
        return max(1.0, min(target, float(max_leverage)))

