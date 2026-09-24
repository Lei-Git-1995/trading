# 脚本迁移指南

从旧版独立脚本迁移到统一框架 v2.0

## 对照表

| 旧脚本 | 新命令 | 说明 |
|--------|--------|------|
| `python eastmoney_stock_analyzer.py 600519` | `python -m stock_analysis 600519` | 自动容灾，更稳定 |
| `python csv_stock_analyzer.py data.csv` | `python -m stock_analysis --csv data.csv --code 600519` | 统一接口 |
| `python stock_analyzer.py 600519` | `python -m stock_analysis 600519` | 保持多主机容灾 |
| `python sina_stock_analyzer.py 600519` | ❌ 已废弃 | 新浪接口不稳定 |
| `python stock_analyzer_akshare.py 600519` | `python -m stock_analysis 600519 --source akshare` | 需先安装akshare |

## 快速脚本（保持原习惯）

如果你习惯直接运行脚本，可以使用 `scripts/analyze_stock.py`：

```bash
# 与旧脚本使用方式完全一样
python scripts/analyze_stock.py 600519
```

## 代码迁移示例

### 1. 东方财富数据源

**旧代码:**
```python
from eastmoney_stock_analyzer import EastMoneyStockAnalyzer

analyzer = EastMoneyStockAnalyzer('600519')
analyzer.generate_report(template_path, output_path)
```

**新代码（方式1 - 推荐）:**
```python
from stock_analysis import StockAnalyzer

# 自动选择最优数据源（包括东方财富）
analyzer = StockAnalyzer('600519')
analyzer.generate_report(output_path)
```

**新代码（方式2 - 指定数据源）:**
```python
from stock_analysis import StockAnalyzer

# 明确使用东方财富
analyzer = StockAnalyzer.from_datasource('600519', 'eastmoney')
analyzer.generate_report(output_path)
```

### 2. CSV数据源

**旧代码:**
```python
from csv_stock_analyzer import CSVStockAnalyzer

analyzer = CSVStockAnalyzer('data.csv', '600519', '贵州茅台')
analyzer.generate_report(template_path, output_path)
```

**新代码:**
```python
from stock_analysis import StockAnalyzer

analyzer = StockAnalyzer.from_csv('data.csv', '600519', '贵州茅台')
analyzer.generate_report(output_path)
```

### 3. 新浪财经数据源

**旧代码:**
```python
from sina_stock_analyzer import SinaStockAnalyzer

analyzer = SinaStockAnalyzer('600519')
analyzer.generate_report(template_path, output_path)
```

**新方案:**
```python
from stock_analysis import StockAnalyzer

# 新浪接口已不稳定，建议使用自动选择
# 框架会自动选择最稳定的数据源
analyzer = StockAnalyzer('600519')
analyzer.generate_report(output_path)
```

## 新功能优势

### 1. 自动容灾

旧版：某个数据源失败，程序直接报错
```python
# 旧代码：东方财富API失败就结束
analyzer = EastMoneyStockAnalyzer('600519')  # 可能失败
```

新版：自动切换备用数据源
```python
# 新代码：东方财富失败会自动尝试腾讯财经
analyzer = StockAnalyzer('600519')  # 自动容灾
```

### 2. 统一接口

旧版：每个数据源API不同
```python
# 5个不同的类，5种初始化方式
EastMoneyStockAnalyzer(code)
CSVStockAnalyzer(file, code, name)
SinaStockAnalyzer(code)
# ...
```

新版：统一接口
```python
# 统一的创建方式
StockAnalyzer(code)
StockAnalyzer.from_csv(file, code, name)
StockAnalyzer.from_datasource(code, source)
```

### 3. 数据验证

新增数据质量检查：
```python
analyzer = StockAnalyzer('600519')
analyzer.load_data()

# 检查数据质量
quality_report = analyzer.get_data_quality_report()
print(quality_report)
```

### 4. 模块化使用

旧版：只能生成完整报告
```python
analyzer = EastMoneyStockAnalyzer('600519')
analyzer.generate_report(template, output)  # 一步完成，无法单独使用
```

新版：可分步操作
```python
analyzer = StockAnalyzer('600519')

# 分步骤执行
df = analyzer.load_data(days=60)
df = analyzer.calculate_indicators()
analysis = analyzer.analyze()
sr = analyzer.get_support_resistance()

# 或者一步完成
analyzer.generate_report()
```

## 配置自定义

### 修改模板路径

**旧版（硬编码）:**
```python
template_path = r"E:\trading\操作手册\stock_analysis_template.md"
analyzer.generate_report(template_path, output_path)
```

**新版（配置文件）:**
```python
# 方式1: 在 config.py 中统一修改
PATHS = {
    'template': Path('新路径/template.md'),
    'reports': Path('新路径/reports/'),
}

# 方式2: 运行时指定
analyzer.generate_report(template_path='custom_template.md')
```

### 修改技术指标参数

**新版支持在 config.py 中配置:**
```python
INDICATOR_PARAMS = {
    'ma_periods': [5, 10, 20, 60, 120],  # 添加120日均线
    'macd': {'fast': 12, 'slow': 26, 'signal': 9},
    'rsi_periods': [6, 12, 24],
    'boll': {'n': 20, 'k': 2.5},  # 修改布林带参数
}
```

## 性能对比

| 方面 | 旧版 | 新版 |
|------|------|------|
| 代码重复率 | ~70% | 0% |
| 单元测试覆盖 | 0% | 架构支持 |
| 容灾能力 | 单点故障 | 多级降级 |
| 可扩展性 | 困难 | 简单 |
| 维护成本 | 5个脚本分别维护 | 统一维护 |

## 常见问题

**Q: 旧脚本还能用吗？**  
A: 可以继续使用，但不会再更新。建议逐步迁移。

**Q: 迁移需要多久？**  
A: 简单替换导入语句即可，5分钟内完成。

**Q: 新版会更慢吗？**  
A: 不会，新版反而因为智能选择数据源而更快。

**Q: 如何保持旧脚本的使用习惯？**  
A: 使用 `scripts/analyze_stock.py`，使用方式完全一样。

**Q: 可以同时使用新旧版本吗？**  
A: 可以，新版是独立的模块，不会影响旧脚本。

## 推荐迁移路径

**第一阶段（1天）:**
1. 安装依赖 `pip install -r stock_analysis/requirements.txt`
2. 测试新版 `python -m stock_analysis 600519`
3. 对比报告结果

**第二阶段（3天）:**
1. 迁移脚本调用：替换导入语句
2. 迁移定时任务：更新cron命令
3. 更新文档：记录新用法

**第三阶段（长期）:**
1. 删除旧脚本（保留备份）
2. 根据需要扩展新功能
3. 提交反馈和改进建议

## 获取帮助

```bash
# 查看所有命令行选项
python -m stock_analysis --help

# 查看数据源状态
python -m stock_analysis --list-sources

# 验证数据质量
python -m stock_analysis 600519 --validate
```
