# 股票选股系统优化说明

## 新增功能

### 1. 日志系统
- 使用 Python logging 模块替代 print
- 支持彩色控制台输出（需要 colorama）
- 自动记录日志到文件：`stock_selector/logs/YYYY-MM-DD.log`
- 可配置日志级别：DEBUG/INFO/WARNING/ERROR

**使用方法**：
```bash
# 默认INFO级别，记录到日志文件
py -3.11 -m stock_selector.main

# 调试模式
py -3.11 -m stock_selector.main --log-level DEBUG

# 不写日志文件
py -3.11 -m stock_selector.main --no-log-file

# 自定义日志文件
py -3.11 -m stock_selector.main --log-file my_log.txt
```

### 2. 预设策略
- 新增 6 个预设策略配置
- 支持通过 `--preset` 参数快速使用
- 命令行参数可覆盖预设值

**可用预设**：
- `default` - 默认策略（换手>15%, 涨幅1-3%）
- `aggressive` - 激进策略（换手>20%, 涨幅3-7%，强放量）
- `conservative` - 保守策略（换手>8%, 涨幅0-3%，过滤创业板/科创板）
- `dip_buying` - 低吸策略（允许小跌，-2%~2%）
- `breakout` - 突破策略（大幅放量>3倍，中等涨幅）
- `mainboard_only` - 主板策略（只选主板股）

**使用方法**：
```bash
# 列出所有预设
py -3.11 -m stock_selector.main --list-presets

# 使用预设策略
py -3.11 -m stock_selector.main --preset aggressive

# 预设 + 自定义参数（命令行参数优先）
py -3.11 -m stock_selector.main --preset conservative --turnover 10
```

### 3. 进度显示
- 在深度分析阶段显示进度条（使用 tqdm）
- 实时显示当前处理进度
- 无 tqdm 时降级为每10只显示一次

### 4. 性能统计
- 自动统计各阶段耗时
- 程序结束时显示完整的性能报告
- 包含：获取行情、策略筛选、生成报告等各阶段时间

**输出示例**：
```
======================================================================
性能统计
======================================================================
策略筛选                        :    45.23秒
获取行情列表                     :     3.21秒
生成报告                        :     0.15秒
======================================================================
```

## 日常使用命令

### 快速开始
```bash
# 使用默认参数
py -3.11 -m stock_selector.main

# 使用激进策略
py -3.11 -m stock_selector.main --preset aggressive

# 使用保守策略
py -3.11 -m stock_selector.main --preset conservative
```

### 自定义参数
```bash
# 完全自定义
py -3.11 -m stock_selector.main --turnover 12 --change 1,5 --volume 1.8

# 预设基础上微调
py -3.11 -m stock_selector.main --preset aggressive --volume 2.0
```

### 其他选项
```bash
# 交互式输入
py -3.11 -m stock_selector.main -i

# 不使用缓存（确保最新数据）
py -3.11 -m stock_selector.main --no-cache

# 调试模式
py -3.11 -m stock_selector.main --log-level DEBUG
```

## 配置文件

预设配置保存在 `stock_selector/presets.yaml`，可以根据需要自定义编辑。

## 依赖安装

新增依赖：
```bash
pip install pyyaml tqdm colorama
```

## 向后兼容

所有原有的命令行参数和用法保持完全兼容，新功能为可选项。

## 日志位置

- 日志文件：`stock_selector/logs/YYYY-MM-DD.log`
- 报告输出：`stock_selector/output/YYYY-MM-DD.md`
