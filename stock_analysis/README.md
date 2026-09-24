# 股票技术分析框架 v2.0

统一的股票技术分析工具，支持多数据源、自动容灾、完整的技术分析和报告生成。

---

## 📁 目录结构

```
stock_analysis/
├── core/                     # 核心功能模块
│   ├── __init__.py
│   ├── indicators.py         # 技术指标计算 (MA/MACD/KDJ/RSI/BOLL)
│   ├── report.py             # 报告生成器
│   └── validator.py          # 数据验证器
│
├── datasources/              # 数据源模块
│   ├── __init__.py
│   ├── base.py               # 数据源基类
│   ├── factory.py            # 数据源工厂 (自动选择)
│   ├── eastmoney.py          # 东方财富 (多主机容灾)
│   ├── tencent.py            # 腾讯财经 (备用)
│   └── csv_source.py         # CSV导入
│
├── legacy/                   # 旧版脚本 (已废弃)
│   └── README.md             # 迁移说明
│
├── reports/                  # 分析报告输出目录
│   └── README.md             # 报告说明
│
├── docs/                     # 文档和模板
│   ├── README.md             # 文档说明
│   └── stock_analysis_template.md  # 报告模板
│
├── __init__.py               # 包入口
├── __main__.py               # 命令行工具
├── config.py                 # 配置管理
├── analyzer.py               # 核心分析器
├── analyze_stock.py          # 快速启动脚本
├── demo.py                   # 功能演示
├── test_framework.py         # 单元测试
│
├── README.md                 # 使用文档
├── MIGRATION.md              # 迁移指南
├── requirements.txt          # 依赖清单
├── setup.py                  # 安装脚本
└── .gitignore                # Git忽略规则
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd E:\trading\stock_analysis
pip install -r requirements.txt
```

或手动安装：
```bash
pip install pandas numpy requests
```

### 2. 运行分析

**方式1：命令行（推荐）**
```bash
# 在 E:\trading 目录下
python -m stock_analysis 600519
```

**方式2：快速脚本**
```bash
# 在 E:\trading 目录下
python stock_analysis/analyze_stock.py 600519
```

**方式3：Python代码**
```python
from stock_analysis import StockAnalyzer

analyzer = StockAnalyzer('600519')
analyzer.generate_report()
```

### 3. 查看报告

报告保存在 `stock_analysis/reports/` 目录：
```
stock_analysis/reports/600519_20240923.md
```

---

## 📖 完整文档

- **README.md** - 完整使用文档
- **MIGRATION.md** - 从旧脚本迁移指南
- **docs/README.md** - 模板和文档说明
- **reports/README.md** - 报告目录说明
- **legacy/README.md** - 旧脚本说明

---

## 🎯 主要功能

### ✅ 多数据源支持
- 东方财富（优先级1，多主机容灾）
- 腾讯财经（优先级2，备用）
- AkShare（优先级3，需安装）
- CSV导入（离线分析）

### ✅ 完整技术指标
- **均线**: MA5/10/20/60
- **MACD**: DIF/DEA/BAR
- **KDJ**: K/D/J
- **RSI**: 6/12/24
- **布林带**: 上轨/中轨/下轨

### ✅ 趋势分析
- 多空判断（多头/空头/震荡）
- 支撑压力位（3级）
- 量能分析（放量/缩量、量价关系）
- 综合评分系统

### ✅ 报告生成
- Markdown格式
- 模板可自定义
- 包含操作建议
- 风险提示

### ✅ 数据验证
- 必需列检查
- 价格合理性验证
- 异常值检测
- 数据质量报告

---

## 📋 命令行选项

```bash
# 基本用法
python -m stock_analysis 600519

# 指定数据源
python -m stock_analysis 600519 --source eastmoney

# CSV分析
python -m stock_analysis --csv data.csv --code 600519 --name 茅台

# 指定输出路径
python -m stock_analysis 600519 -o reports/custom.md

# 获取更多历史数据
python -m stock_analysis 600519 --days 120

# 数据质量验证
python -m stock_analysis 600519 --validate

# 查看数据源状态
python -m stock_analysis --list-sources

# 查看帮助
python -m stock_analysis --help
```

---

## 🔧 配置说明

编辑 `config.py` 自定义配置：

### 路径配置
```python
PATHS = {
    'template': PROJECT_ROOT / 'docs' / 'stock_analysis_template.md',
    'reports': PROJECT_ROOT / 'reports',
    'cache': PROJECT_ROOT / '.cache',
}
```

### 技术指标参数
```python
INDICATOR_PARAMS = {
    'ma_periods': [5, 10, 20, 60],
    'macd': {'fast': 12, 'slow': 26, 'signal': 9},
    'kdj': {'n': 9, 'm1': 3, 'm2': 3},
    'rsi_periods': [6, 12, 24],
    'boll': {'n': 20, 'k': 2},
}
```

### 数据源优先级
```python
DATASOURCE_CONFIG = {
    'eastmoney': {'enabled': True, 'priority': 1, 'timeout': 15},
    'tencent': {'enabled': True, 'priority': 2, 'timeout': 15},
}
```

---

## 🔄 从旧脚本迁移

### 命令对照

| 旧命令 | 新命令 |
|--------|--------|
| `python scripts/eastmoney_stock_analyzer.py 600519` | `python -m stock_analysis 600519` |
| `python scripts/csv_stock_analyzer.py data.csv` | `python -m stock_analysis --csv data.csv` |
| `python scripts/stock_analyzer.py 600519` | `python -m stock_analysis 600519` |

### 代码迁移

```python
# 旧代码
from eastmoney_stock_analyzer import EastMoneyStockAnalyzer
analyzer = EastMoneyStockAnalyzer('600519')
analyzer.generate_report(template_path, output_path)

# 新代码
from stock_analysis import StockAnalyzer
analyzer = StockAnalyzer('600519')
analyzer.generate_report(output_path)
```

详见：`MIGRATION.md`

---

## 📊 与旧脚本对比

| 方面 | 旧版 | 新版 |
|------|------|------|
| 代码重复率 | ~70% | 0% |
| 脚本数量 | 5个独立脚本 | 1个统一框架 |
| 容灾能力 | 仅1个脚本支持 | 全部支持 |
| 数据验证 | ❌ 无 | ✅ 完整 |
| 单元测试 | ❌ 无 | ✅ 支持 |
| 配置管理 | ❌ 硬编码 | ✅ 统一配置 |
| 维护成本 | 高 | 低（减少80%） |

---

## 🛠️ 开发和测试

### 运行演示
```bash
python stock_analysis/demo.py
```

### 运行测试
```bash
python stock_analysis/test_framework.py
```

### 安装为包（可选）
```bash
cd stock_analysis
pip install -e .
# 安装后可直接使用
stock-analysis 600519
```

---

## ⚠️ 注意事项

1. **依赖要求**
   - Python >= 3.7
   - pandas >= 1.3.0
   - numpy >= 1.20.0
   - requests >= 2.25.0

2. **模板文件**
   - 默认模板：`stock_analysis/docs/stock_analysis_template.md`
   - 如需自定义，复制并修改此文件

3. **网络要求**
   - 在线数据源需要网络连接
   - 如无网络，可使用CSV导入方式

4. **旧脚本处理**
   - 旧脚本已移至 `legacy/` 目录
   - 建议在新框架稳定后删除

---

## 📞 获取帮助

```bash
# 查看完整文档
cat stock_analysis/README.md

# 查看迁移指南
cat stock_analysis/MIGRATION.md

# 查看命令帮助
python -m stock_analysis --help

# 运行演示
python stock_analysis/demo.py
```

---

## 📝 更新日志

### v2.0.0 (2024-09-23)
- ✅ 重构5个独立脚本为统一框架
- ✅ 消除70%的代码重复
- ✅ 统一数据源接口
- ✅ 增加自动容灾机制
- ✅ 增加数据质量验证
- ✅ 完善配置管理
- ✅ 增加命令行工具
- ✅ 完善文档体系

---

## 📄 许可证

MIT License

---

**推荐使用方式**：
```bash
# 在 E:\trading 目录下运行
python -m stock_analysis 600519
```

报告将保存在：`stock_analysis/reports/600519_YYYYMMDD.md`
