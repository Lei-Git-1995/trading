from freqtrade.strategy import IStrategy
import talib.abstract as ta


class EMAStartStrategy(IStrategy):
    """简单 EMA 交叉示例，仅用于学习、回测和 Dry-run。"""

    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "15m"
    startup_candle_count = 50
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.03,
        "60": 0.01,
        "120": 0
    }
    stoploss = -0.05

    def populate_indicators(self, dataframe, metadata):
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
                & (dataframe["rsi"] > 50)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[
            (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1))
            ),
            "exit_long",
        ] = 1
        return dataframe
