"""OKX 模拟盘：5m 短线高抛低吸（多空双向）。

做多：上升趋势中价格回踩布林下轨、RSI 超卖、当根收回阳线 -> 买入，目标对侧上轨。
做空：下降趋势中价格冲上布林上轨、RSI 超买、当根收回阴线 -> 卖出，目标对侧下轨。
200 均线作为趋势过滤，避免逆势接刀。
"""
from freqtrade.strategy import (
    IStrategy,
    IntParameter,
    DecimalParameter,
    BooleanParameter,
)
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

    buy_rsi = IntParameter(15, 40, default=21, space="buy", optimize=True, load=True)
    sell_rsi = IntParameter(60, 85, default=79, space="sell", optimize=True, load=True)
    bb_width_max = DecimalParameter(0.03, 0.15, default=0.091, space="buy",
                                    optimize=True, load=True)
    nbdev = DecimalParameter(1.5, 3.0, default=1.899, space="buy", optimize=True, load=True)
    trend_ema = IntParameter(100, 300, default=180, space="buy", optimize=True, load=True)
    rsi_period = IntParameter(5, 14, default=7, space="buy", optimize=True, load=True)
    bb_period = IntParameter(15, 30, default=20, space="buy", optimize=True, load=True)
    adx_max = IntParameter(20, 50, default=50, space="buy", optimize=True, load=True)
    use_adx = BooleanParameter(default=False, space="buy", optimize=True, load=True)

    @property
    def _short_enabled(self) -> bool:
        return bool(self.config.get("mr_enable_short", True))

    def populate_indicators(self, dataframe, metadata):
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=int(self.trend_ema.value))
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=int(self.rsi_period.value))
        bb = ta.BBANDS(dataframe["close"], timeperiod=int(self.bb_period.value),
                       nbdevup=float(self.nbdev.value), nbdevdn=float(self.nbdev.value),
                       matype=0)
        dataframe["bb_upper"] = bb[0]
        dataframe["bb_mid"] = bb[1]
        dataframe["bb_lower"] = bb[2]
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["close"]
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        liquid = dataframe["volume"] > 0
        ranging = dataframe["bb_width"] < self.bb_width_max.value
        calm = (dataframe["adx"] < self.adx_max.value) | (not self.use_adx.value)

        dip_buy = (
            (dataframe["rsi"] <= self.buy_rsi.value)
            & (dataframe["low"] <= dataframe["bb_lower"])
            & (dataframe["close"] > dataframe["open"])
            & (dataframe["close"] > dataframe["ema_trend"])
            & ranging
            & calm
            & liquid
        )
        rally_sell = (
            (dataframe["rsi"] >= self.sell_rsi.value)
            & (dataframe["high"] >= dataframe["bb_upper"])
            & (dataframe["close"] < dataframe["open"])
            & (dataframe["close"] < dataframe["ema_trend"])
            & ranging
            & calm
            & liquid
            & self._short_enabled
        )
        dataframe.loc[dip_buy, ["enter_long", "enter_tag"]] = (1, "dip_buy")
        dataframe.loc[rally_sell, ["enter_short", "enter_tag"]] = (1, "rally_sell")
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        liquid = dataframe["volume"] > 0
        long_target = (
            ((dataframe["rsi"] >= self.sell_rsi.value)
             | (dataframe["close"] >= dataframe["bb_upper"]))
            & liquid
        )
        short_target = (
            ((dataframe["rsi"] <= self.buy_rsi.value)
             | (dataframe["close"] <= dataframe["bb_lower"]))
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
