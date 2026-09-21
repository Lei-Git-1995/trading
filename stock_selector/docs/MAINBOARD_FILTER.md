# 主板股票过滤功能

## 功能说明

新增 `--mainboard-only` 参数，可以一键过滤创业板和科创板，只保留主板股票。

## 使用方法

### 方法1：使用命令行参数

```bash
# 只选主板股票
py -3.11 -m stock_selector.main --mainboard-only

# 结合其他参数
py -3.11 -m stock_selector.main --mainboard-only --turnover 12 --change 1,5

# 结合预设策略
py -3.11 -m stock_selector.main --preset aggressive --mainboard-only
```

### 方法2：使用预设策略

```bash
# 使用 mainboard_only 预设（已配置好主板模式）
py -3.11 -m stock_selector.main --preset mainboard_only
```

### 方法3：在 YAML 配置中定义

编辑 `presets.yaml` 文件，在任何预设中添加：

```yaml
your_preset:
  turnover: 15.0
  change: [1, 3]
  volume: 1.5
  mainboard_only: true  # 添加这一行
```

## 效果对比

### 不使用 --mainboard-only
- 包含所有A股：主板 + 创业板 + 科创板
- 代码范围：000xxx, 002xxx, 300xxx, 600xxx, 601xxx, 603xxx, 688xxx

### 使用 --mainboard-only
- 只包含主板股票
- 代码范围：000xxx, 002xxx, 600xxx, 601xxx, 603xxx
- 自动过滤：
  - ❌ 创业板（300xxx）
  - ❌ 科创板（688xxx）

## 等价命令

以下命令效果相同：

```bash
# 方式1：使用 --mainboard-only
py -3.11 -m stock_selector.main --mainboard-only

# 方式2：分别指定过滤
py -3.11 -m stock_selector.main --no-cyb --no-kcb

# 方式3：使用预设
py -3.11 -m stock_selector.main --preset mainboard_only
```

## 适用场景

### 推荐使用主板模式的情况：
- ✅ 偏好大盘蓝筹股
- ✅ 风险承受能力较低
- ✅ 看重企业基本面和稳定性
- ✅ 不喜欢高波动个股

### 不推荐使用主板模式的情况：
- ❌ 追求高成长性股票
- ❌ 喜欢科技题材
- ❌ 短线追涨策略

## 预设策略对比

| 预设名称 | 是否过滤创业板/科创板 | 适用场景 |
|---------|---------------------|---------|
| `default` | ❌ 不过滤 | 日常选股 |
| `aggressive` | ❌ 不过滤 | 捕捉强势股 |
| `conservative` | ✅ 过滤 | 稳健投资 |
| `dip_buying` | ❌ 不过滤 | 低吸反弹 |
| `breakout` | ❌ 不过滤 | 放量突破 |
| `mainboard_only` | ✅ 过滤 | 主板稳健 |

## 示例

### 示例1：日常主板选股
```bash
py -3.11 -m stock_selector.main --mainboard-only
```

### 示例2：主板激进策略
```bash
py -3.11 -m stock_selector.main --preset aggressive --mainboard-only --turnover 20 --change 3,7
```

### 示例3：自定义主板策略
```bash
py -3.11 -m stock_selector.main --mainboard-only --turnover 10 --change 0,4 --volume 1.5
```

---

**提示**：如果你偏好稳健投资，建议默认使用 `--mainboard-only` 参数！
