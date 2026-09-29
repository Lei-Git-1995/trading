# v2 架构使用指南

## 🎉 新功能上线

已完成 **v2 多维度评分架构**，现在可以使用全新的超短线策略！

## 🚀 快速开始

### 1. 查看所有 v2 策略
```bash
cd E:\trading
py -3.11 -m stock_selector.main --list-v2
```

### 2. 使用 v2 策略选股

**超短线启动策略**（推荐）:
```bash
py -3.11 -m stock_selector.main --preset-v2 ultra_short
```

**启动策略**（偏保守）:
```bash
py -3.11 -m stock_selector.main --preset-v2 momentum_start
```

**弱转强策略**:
```bash
py -3.11 -m stock_selector.main --preset-v2 weak_to_strong
```

### 3. 测试新架构
```bash
py -3.11 stock_selector/test_v2.py
```

## 📊 v2 vs v1 对比

### v1 架构（现有）
```
单层硬过滤: 换手率>15% AND 涨幅1~3% AND 量比>1.5
↓
通过/不通过
```

**缺点**:
- 只有3个维度
- 非黑即白，没有灰度
- 无法识别相对强度、趋势位置等

### v2 架构（新）
```
多维度评分:
  基础过滤（硬条件）
    ↓
  信号评分（100分）
    - 动能信号（25分）
    - 技术信号（20分）
    - 资金信号（25分）
    - 量价信号（15分）
    - 形态信号（15分）
    ↓
  风险控制（扣分）
    ↓
  综合排序 → Top N
```

**优势**:
- ✅ 10+ 维度综合评价
- ✅ 相对强度（强于板块）
- ✅ 趋势位置（MA20距离）
- ✅ 资金流向（主力流入）
- ✅ 风险控制（连续上涨扣分）
- ✅ 灵活评分（不是非黑即白）

## 🎯 v2 策略特点

### ultra_short（超短线启动）
**适合**: 1-2日持仓，不追高

**核心逻辑**:
- 涨幅2-7%（不追已经大涨的）
- 强于板块至少1%
- 主力资金流入>500万
- 距MA20不远（-3%~15%）
- 突破20日高点
- 5日涨幅<20%（防止追高）

**风险控制**:
- 连续上涨5天扣20分
- 距MA20超20%扣15分
- 3日涨超30%扣25分

### momentum_start（启动策略）
**适合**: 偏保守，寻找启动点

**核心逻辑**:
- 涨幅1.5-5%（更保守）
- 技术位置好（在MA20附近）
- 主力资金流入>800万
- 不选科创板

### weak_to_strong（弱转强）
**适合**: 寻找前一日弱势今日转强

**核心逻辑**:
- 今日涨幅3-8%
- 动能加速（比昨日强）
- 主力资金流入>1000万
- 成交量突然放大

## 📁 输出文件

v2 策略的报告文件名带有策略名称:
```
output/2026-09-23_v2_ultra_short.md
output/2026-09-23_v2_momentum_start.md
```

## 🔧 技术架构

### 新增模块

**数据层**:
- `data/sector_client.py` - 板块数据（计算相对强度）
- `data/intraday_client.py` - 分时数据（日内最高价距离）
- `data/capital_flow_client.py` - 资金流向

**指标层**:
- `indicators/advanced_indicators.py` - 高级指标
  - relative_strength (相对强度)
  - ma_position (均线位置)
  - consecutive_days (连续涨跌)
  - breakout_detection (突破识别)
  - platform_detection (平台突破)

**策略层**:
- `strategies/scoring_engine.py` - 评分引擎
- `strategies/strategy_adapter.py` - 策略适配器

**配置**:
- `presets_v2.yaml` - v2策略配置

## 💡 使用建议

1. **首次使用**: 先运行 `test_v2.py` 确保环境正常
2. **对比验证**: 同时运行 v1 和 v2 策略，对比结果
3. **参数调整**: 编辑 `presets_v2.yaml` 自定义策略参数
4. **数据缓存**: 首次运行较慢，后续会使用缓存

## 🐛 常见问题

### Q: 运行报错 "ModuleNotFoundError"?
A: 确保在 E:\trading 目录下运行

### Q: 数据获取失败?
A: 检查网络，东方财富API可能限流

### Q: 评分结果为空?
A: 标准较严格，可以降低 min_score 或调整筛选条件

### Q: v1 和 v2 可以同时用吗?
A: 可以！v2 完全独立，不影响 v1 策略

## 📈 下一步计划

- [ ] 完善报告输出（增加评分明细）
- [ ] 增加更多 v2 策略（打板、开盘攻击）
- [ ] 优化性能（并行计算、缓存）
- [ ] 回测功能（验证策略有效性）

---

**祝您选股顺利！** 📈

有任何问题请反馈。
