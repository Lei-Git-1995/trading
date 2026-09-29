# 技术指标与周期形态选股策略

技术策略入口为 `python -m stock_selector.strategy_runner`，数据获取复用 `stock_selector.data.providers`，策略实现位于 `strategies/technical_selection.py`。

## 指标配置

模块使用 MA5/10/20/60/120、EMA12/26/50、MACD(12,26,9)、KDJ(9,3,3)、RSI6/12/24、BOLL(20,2)、成交量均线5/20、ATR14和OBV20。ADX暂未加入计算，现有系统的评分策略仍可继续使用自己的指标逻辑。

## 策略

1. **均线多头趋势**：MA5>MA10>MA20，收盘在MA20上方，MA20较5个交易日前上行。
2. **MACD金叉**：近3日 DIF 上穿 DEA，MACD红柱，收盘在MA20上方。
3. **RSI回升**：RSI6在35至65之间并回升，RSI12不低于45。
4. **布林上轨突破**：收盘突破BOLL上轨，量比不低于1.2。
5. **放量突破**：收盘突破前20日高点，涨幅为正，量比不低于1.5。
6. **温和连续上涨吸筹**：最近10日内连续3天上涨，每天涨幅1%-3%，且价格在MA20上方。该规则是技术代理信号，不能单独证明主力吸筹。
7. **回撤后反弹**：近10日早段回撤至少5%，最新价格站回MA5并上涨。
8. **多因子综合**：趋势、MACD、量价、RSI、布林五项中至少满足三项。

策略结果只表示历史数据满足规则，仍需结合 ST/退市、停牌、涨跌停、流动性、行业、基本面和止损规则进行复核，并通过历史回测评估稳定性。

## 使用

```powershell
cd E:\trading
python -m stock_selector.strategy_runner --list-strategies
python -m stock_selector.strategy_runner --strategy all --limit 100
python -m stock_selector.strategy_runner --strategy accumulation_3of10 --codes 600519,600036
```

不传 `--strategy` 时会显示策略列表并进入交互选择。报告默认写入 `stock_selector/output/technical_YYYY-MM-DD_HHMMSS.md`。
