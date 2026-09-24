# 快速开始指南

## 1️⃣ 安装依赖（必需）

```bash
cd E:\trading
pip install pandas numpy requests
```

如果需要使用AkShare数据源：
```bash
pip install akshare
```

## 2️⃣ 测试运行

### 测试1: 运行演示程序

```bash
cd E:\trading
python stock_analysis/demo.py
```

**预期输出**:
```
# 示例1: 技术指标计算
原始数据: 100 行
添加技术指标后: 21 列
最新指标值:
  MA5:  105.23
  MACD_DIF: 0.1234
  ...
```

### 测试2: 分析真实股票

```bash
# 方式1: 模块方式（推荐）
python -m stock_analysis 600519

# 方式2: 快速脚本
python scripts/analyze_stock.py 600519
```

**预期输出**:
```
============================================================
  股票技术分析工具 v2.0
============================================================

尝试数据源: eastmoney
OK 使用主机: push2delay.eastmoney.com

[1/3] 获取 600519 实时行情...
  OK 贵州茅台 (600519)

[2/3] 获取历史K线数据...
  OK 成功获取 60 天K线数据

[3/3] 计算技术指标...
  OK 技术指标计算完成

正在分析趋势...
✓ 趋势: 多头排列,趋势向上
✓ MACD: 金叉 (看多)
✓ KDJ: 正常

支撑位: 1650.00, 1620.00, 1600.00
压力位: 1720.00, 1750.00, 1780.00

正在生成分析报告...
✓ 报告已生成: E:\trading\reports\600519_20240923.md

============================================================
✓ 分析完成!
  报告路径: E:\trading\reports\600519_20240923.md
============================================================
```

## 3️⃣ 常用命令

### 分析股票

```bash
# 自动选择最优数据源
python -m stock_analysis 600519

# 指定东方财富数据源
python -m stock_analysis 600519 --source eastmoney

# 指定输出路径
python -m stock_analysis 600519 -o reports/茅台分析.md

# 获取更多历史数据
python -m stock_analysis 600519 --days 120
```

### 从CSV分析

```bash
python -m stock_analysis --csv data.csv --code 600519 --name 贵州茅台
```

### 工具命令

```bash
# 查看所有可用数据源
python -m stock_analysis --list-sources

# 验证数据质量
python -m stock_analysis 600519 --validate

# 查看帮助
python -m stock_analysis --help

# 查看版本
python -m stock_analysis --version
```

## 4️⃣ Python代码使用

### 最简单的方式

```python
from stock_analysis import StockAnalyzer

# 一行代码生成报告
analyzer = StockAnalyzer('600519')
analyzer.generate_report()
```

### 分步操作

```python
from stock_analysis import StockAnalyzer

# 创建分析器
analyzer = StockAnalyzer('600519')

# 加载数据
df = analyzer.load_data(days=60)
print(f"获取了 {len(df)} 天数据")

# 计算技术指标
analyzer.calculate_indicators()

# 执行分析
analysis = analyzer.analyze()
print(f"趋势: {analysis['trend']}")
print(f"MACD: {analysis['macd_status']}")

# 获取支撑压力位
sr = analyzer.get_support_resistance()
print(f"支撑位: {sr['supports']}")
print(f"压力位: {sr['resistances']}")

# 生成报告
report_path = analyzer.generate_report()
print(f"报告已生成: {report_path}")
```

### 使用CSV数据

```python
from stock_analysis import StockAnalyzer

# 从CSV创建分析器
analyzer = StockAnalyzer.from_csv(
    'stock_data.csv',
    stock_code='600519',
    stock_name='贵州茅台'
)

# 生成报告
analyzer.generate_report()
```

### 指定数据源

```python
from stock_analysis import StockAnalyzer

# 明确使用东方财富
analyzer = StockAnalyzer.from_datasource('600519', 'eastmoney')
analyzer.generate_report()

# 明确使用腾讯财经
analyzer = StockAnalyzer.from_datasource('600519', 'tencent')
analyzer.generate_report()
```

### 数据质量检查

```python
from stock_analysis import StockAnalyzer

analyzer = StockAnalyzer('600519')
analyzer.load_data()

# 获取数据质量报告
quality = analyzer.get_data_quality_report()
print(f"总行数: {quality['total_rows']}")
print(f"日期范围: {quality['date_range']}")
print(f"缺失值: {quality['missing_values']}")
```

## 5️⃣ 配置自定义

编辑 `stock_analysis/config.py`:

### 修改路径

```python
PATHS = {
    'template': Path('E:/trading/templates/my_template.md'),
    'reports': Path('E:/trading/my_reports'),
}
```

### 修改技术指标参数

```python
INDICATOR_PARAMS = {
    'ma_periods': [5, 10, 20, 60, 120],  # 添加120日均线
    'macd': {'fast': 12, 'slow': 26, 'signal': 9},
    'kdj': {'n': 9, 'm1': 3, 'm2': 3},
    'rsi_periods': [6, 12, 24],
    'boll': {'n': 20, 'k': 2.5},  # 修改布林带宽度
}
```

### 修改数据源优先级

```python
DATASOURCE_CONFIG = {
    'eastmoney': {
        'enabled': True,
        'priority': 1,  # 优先级1（最高）
        'timeout': 15,
    },
    'tencent': {
        'enabled': True,
        'priority': 2,  # 优先级2
        'timeout': 15,
    },
}
```

## 6️⃣ 故障排查

### 问题1: ModuleNotFoundError

**错误**: `ModuleNotFoundError: No module named 'pandas'`

**解决**:
```bash
pip install pandas numpy requests
```

### 问题2: 模板文件不存在

**错误**: `FileNotFoundError: 模板文件不存在`

**解决**:
1. 检查 `E:\trading\操作手册\stock_analysis_template.md` 是否存在
2. 或在 `config.py` 中修改模板路径

### 问题3: 所有数据源均不可用

**错误**: `Exception: 所有数据源均不可用`

**解决**:
1. 检查网络连接
2. 尝试单独测试数据源：
   ```bash
   python -m stock_analysis --list-sources
   ```
3. 使用CSV数据作为替代方案

### 问题4: 中文乱码

**Windows CMD乱码解决**:
```bash
chcp 65001
python -m stock_analysis 600519
```

或使用 PowerShell / Git Bash

## 7️⃣ 常见股票代码

```
贵州茅台: 600519
招商银行: 600036
平安银行: 000001
五粮液:   000858
中国平安: 601318
兴业银行: 601166
宁德时代: 300750
比亚迪:   002594
```

## 8️⃣ 输出示例

运行成功后，会在 `E:\trading\reports\` 目录下生成Markdown格式报告：

```
E:\trading\reports\600519_20240923.md
```

报告包含：
- 📊 基本信息（代码、名称、行业）
- 💹 实时行情（最新价、涨跌幅等）
- 📈 近10日数据表格
- 📉 技术指标（MA/MACD/KDJ/RSI/BOLL）
- 🎯 趋势分析
- 📍 支撑压力位
- 💡 操作建议
- ⚠️ 风险提示

## 9️⃣ 获取帮助

```bash
# 查看所有命令选项
python -m stock_analysis --help

# 查看README文档
cat stock_analysis/README.md

# 查看迁移指南
cat stock_analysis/MIGRATION.md

# 查看重构总结
cat REFACTORING_SUMMARY.md
```

## 🎯 下一步

1. ✅ 运行 `demo.py` 验证框架
2. ✅ 测试分析真实股票
3. ✅ 查看生成的报告
4. ✅ 根据需要调整配置
5. ✅ 迁移旧脚本调用

---

**需要更多帮助？**
- 查看 `stock_analysis/README.md` - 完整文档
- 查看 `stock_analysis/MIGRATION.md` - 迁移指南
- 查看 `REFACTORING_SUMMARY.md` - 重构说明
