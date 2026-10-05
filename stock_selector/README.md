# 股票选股系统

`stock_selector` 是一个面向沪深 A 股的短线选股系统，支持多数据源、预设策略、技术指标筛选、v2 多维度评分和 Markdown 报告输出。

## 目录结构

```text
stock_selector/
├── main.py                         # 常规短线选股入口
├── strategy_runner.py              # 技术形态选股入口
├── config.py                       # 全局配置和筛选参数
├── presets.yaml                    # 常规预设策略
├── presets_v2.yaml                 # v2 评分策略
├── data/                           # 数据源、缓存和行情标准化
├── indicators/                     # KDJ、RSI、成交量等指标
├── strategies/                     # 常规、v2 和技术形态策略
├── reports/                        # Markdown/Excel 报告生成
├── utils/                          # 日志、配置加载、计时工具
├── docs/                           # 使用、架构和维护文档
├── output/                         # 选股报告输出目录
└── logs/                           # 运行日志目录
```

## 快速开始

```powershell
cd E:\trading
py -3.11 -m stock_selector.main --list-presets
py -3.11 -m stock_selector.main --preset conservative
```

技术形态选股：

```powershell
py -3.11 -m stock_selector.strategy_runner --list-strategies
py -3.11 -m stock_selector.strategy_runner --strategy ma_trend --limit 100
```

完整使用说明请查看 [文档目录](docs/文档目录.md)。
