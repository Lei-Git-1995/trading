# 股票选股系统 - 快速使用指南

## 一、日常执行命令

### 1. 使用默认参数
```bash
cd E:\trading
py -3.11 -m stock_selector.main
```

### 2. 使用预设策略（推荐）

**查看所有预设**：
```bash
py -3.11 -m stock_selector.main --list-presets
```

**激进策略**（捕捉强势股）：
```bash
py -3.11 -m stock_selector.main --preset aggressive
```

**保守策略**（稳健标的，过滤创业板/科创板）：
```bash
py -3.11 -m stock_selector.main --preset conservative
```

**低吸策略**（允许小跌，寻找反弹机会）：
```bash
py -3.11 -m stock_selector.main --preset dip_buying
```

**突破策略**（大幅放量突破）：
```bash
py -3.11 -m stock_selector.main --preset breakout
```

### 3. 自定义参数

**完全自定义**：
```bash
py -3.11 -m stock_selector.main --turnover 12 --change 1,5 --volume 1.8
```

**在预设基础上微调**：
```bash
# 使用激进策略，但降低量能要求
py -3.11 -m stock_selector.main --preset aggressive --volume 2.0

# 使用保守策略，但调整涨幅区间
py -3.11 -m stock_selector.main --preset conservative --change 0,2
```

### 4. 其他实用选项

**交互式输入**（适合探索不同参数）：
```bash
py -3.11 -m stock_selector.main -i
```

**不使用缓存**（确保最新数据）：
```bash
py -3.11 -m stock_selector.main --no-cache
```

**调试模式**（显示详细日志）：
```bash
py -3.11 -m stock_selector.main --log-level DEBUG
```

**不记录日志文件**：
```bash
py -3.11 -m stock_selector.main --no-log-file
```

## 二、预设策略说明

| 预设名称 | 换手率 | 涨跌幅 | 量能 | 适用场景 |
|---------|--------|--------|------|---------|
| `default` | >15% | 1~3% | >1.5倍 | 日常选股，适中标准 |
| `aggressive` | >20% | 3~7% | >2.5倍 | 捕捉强势股，追涨 |
| `conservative` | >8% | 0~3% | >1.2倍 | 稳健标的，过滤创业板/科创板 |
| `dip_buying` | >12% | -2~2% | >1.8倍 | 低吸反弹，允许小跌 |
| `breakout` | >18% | 2~5% | >3.0倍 | 放量突破，不限制超买 |
| `mainboard_only` | >12% | 1~4% | >1.5倍 | 只选主板股 |

## 三、输出文件

- **选股报告**：`stock_selector/output/YYYY-MM-DD.md`
- **日志文件**：`stock_selector/logs/YYYY-MM-DD.log`

## 四、参数说明

### 筛选参数
- `--turnover`: 最低换手率（%），默认15
- `--change`: 涨跌幅区间（%），格式：最小值,最大值，如 `1,3` 或 `-2,2`
- `--volume`: 量能放大倍数，默认1.5
- `--sector`: 每个板块最多数量，默认20（0不限制）

### 过滤选项
- `--no-outer`: 不检查外盘内盘关系
- `--no-kdj`: 不检查KDJ超买（K<80）
- `--no-rsi`: 不检查RSI超买（RSI6<70）
- `--no-cyb`: 过滤创业板（3开头）
- `--no-kcb`: 过滤科创板（688开头）

### 数据源
- `--source`: 指定数据源（eastmoney/tencent/akshare），默认东方财富

### 日志选项
- `--log-level`: 日志级别（DEBUG/INFO/WARNING/ERROR），默认INFO
- `--log-file`: 日志文件路径
- `--no-log-file`: 不写入日志文件

## 五、典型使用场景

### 场景1：每日盘后选股（推荐）
```bash
# 使用默认策略
py -3.11 -m stock_selector.main

# 或使用激进策略
py -3.11 -m stock_selector.main --preset aggressive
```

### 场景2：寻找反弹机会
```bash
py -3.11 -m stock_selector.main --preset dip_buying
```

### 场景3：只看主板股
```bash
py -3.11 -m stock_selector.main --preset mainboard_only
```

### 场景4：探索最佳参数
```bash
# 交互式输入，多次尝试不同参数组合
py -3.11 -m stock_selector.main -i
```

### 场景5：调试问题
```bash
py -3.11 -m stock_selector.main --log-level DEBUG --no-cache
```

## 六、新功能亮点

### 1. 日志系统
- ✅ 彩色控制台输出
- ✅ 自动记录到文件
- ✅ 可配置日志级别

### 2. 预设策略
- ✅ 6种预设策略快速切换
- ✅ 支持预设+自定义参数组合
- ✅ 可扩展（编辑 `presets.yaml`）

### 3. 进度显示
- ✅ 深度分析阶段实时进度条
- ✅ 显示当前处理的股票数量

### 4. 性能统计
- ✅ 自动统计各阶段耗时
- ✅ 程序结束显示完整报告

## 七、常见问题

### Q: 如何添加自定义预设？
A: 编辑 `stock_selector/presets.yaml` 文件，参考现有预设格式添加新的配置。

### Q: 日志文件在哪里？
A: 默认在 `stock_selector/logs/YYYY-MM-DD.log`

### Q: 如何关闭进度条？
A: 卸载 tqdm：`pip uninstall tqdm`（系统会自动降级为简单进度提示）

### Q: 预设和命令行参数冲突怎么办？
A: 命令行参数优先级更高，会覆盖预设中的对应值。

## 八、依赖安装

如果是新环境，需要安装以下依赖：
```bash
pip install pandas numpy requests akshare pyyaml tqdm colorama
```

---

**提示**：首次运行建议使用 `--list-presets` 查看所有预设策略，选择最适合你的！
