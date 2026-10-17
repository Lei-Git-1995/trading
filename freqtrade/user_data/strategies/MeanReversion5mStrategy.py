"""OKX demo futures: short-term mean-reversion ("high sell / low buy") on 5m, long and short.

Long: an uptrend candle dips to the lower Bollinger band, RSI is stretched and the
candle closes back up -> buy, target the mid-band. Short is the mirror image.
The 200-EMA is the trend filter so we never fade a strong move.
"""
from freqtrade.strategy import IStrategy
import talib.abstract as ta


class MeanReversion5mStrategy(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "5m"
    startup_candle_count = 220
    process_only_new_candles = True
    use_exit_signal = True
    position_adjustment_enable = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 3},
        {"method": "StoplossGuard", "lookback_period_candles": 288,
         "trade_limit": 3, "stop_duration_candles": 36, "only_per_pair": True},
        {"method": "MaxDrawdown", "lookback_period_candles": 576,
         "trade_limit": 5, "stop_duration_candles": 144,
         "max_allowed_drawdown": 0.12, "calculation_mode": "equity"},
    ]
    stoploss = -0.05
    minimal_roi = {"0": 0.04, "30": 0.025, "90": 0.012, "180": 0}

    def populate_indicators(self, dataframe, metadata):
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=7)
        bb = ta.BBANDS(dataframe["close"], timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
        dataframe["bb_upper"] = bb[0]
        dataframe["bb_mid"] = bb[1]
        dataframe["bb_lower"] = bb[2]
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["close"]
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        liquid = dataframe["volume"] > 0
        ranging = dataframe["bb_width"] < 0.08

        dip_buy = (
            (dataframe["rsi"] <= 30)
            & (dataframe["low"] <= dataframe["bb_lower"])
            & (dataframe["close"] > dataframe["open"])
            & (dataframe["close"] > dataframe["ema_trend"])
            & ranging
            & liquid
        )
        rally_sell = (
            (dataframe["rsi"] >= 70)
            & (dataframe["high"] >= dataframe["bb_upper"])
            & (dataframe["close"] < dataframe["open"])
            & (dataframe["close"] < dataframe["ema_trend"])
            & ranging
            & liquid
        )
        dataframe.loc[dip_buy, ["enter_long", "enter_tag"]] = (1, "dip_buy")
        dataframe.loc[rally_sell, ["enter_short", "enter_tag"]] = (1, "rally_sell")
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        liquid = dataframe["volume"] > 0
        long_target = (
            ((dataframe["rsi"] >= 70) | (dataframe["close"] >= dataframe["bb_upper"]))
            & liquid
        )
        short_target = (
            ((dataframe["rsi"] <= 30) | (dataframe["close"] <= dataframe["bb_lower"]))
            & liquid
        )
        dataframe.loc[long_target, ["exit_long", "exit_tag"]] = (1, "mr_target")
        dataframe.loc[short_target, ["exit_short", "exit_tag"]] = (1, "mr_target")
        return dataframe

    def leverage(
        self, pair, current_time, current_rate, proposed_leverage,
        max_leverage, entry_tag, side, **kwargs
    ) -> float:
        return 1.0
