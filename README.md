# Trading 项目目录结构说明

## 📁 整体结构

```
E:\trading\
│
├── stock_analysis/          ✅ 【技术分析模块】
│   ├── core/                   # 核心功能
│   ├── datasources/            # 数据源
│   ├── legacy/                 # 旧脚本归档
│   ├── reports/                # 分析报告
│   ├── docs/                   # 文档和模板
│   └── *.py                    # 主程序文件
│
├── stock_selector/          ✅ 【条件选股模块】
│   └── ...                     # 选股相关代码
│
├── project/                 ✅ 【实战项目】
│   └── stock/                  # 实战工程
│
├── scripts/                 📂 【脚本目录】
│   └── (已清空，旧脚本移至 stock_analysis/legacy/)
│
├── reports/                 📂 【旧报告目录】
│   └── (建议迁移到 stock_analysis/reports/)
│
├── 操作手册/                📂 【旧文档目录】
│   └── (建议复制到 stock_analysis/docs/)
│
└── stock/                   📂 【旧目录】
    └── (暂不处理)
```

---

## 🎯 各模块定位

### 1. stock_analysis/ - 技术分析

**用途**: 股票技术分析和报告生成

**主要功能**:
- 获取股票实时和历史数据
- 计算技术指标（MA/MACD/KDJ/RSI/BOLL）
- 趋势分析和支撑压力位
- 生成分析报告

**使用方式**:
```bash
# 在 E:\trading 目录下
python -m stock_analysis 600519
```

**特点**:
- ✅ 多数据源（东方财富/腾讯/AkShare/CSV）
- ✅ 自动容灾
- ✅ 完整技术指标
- ✅ 报告生成

**文档**: `stock_analysis/README.md`

---

### 2. stock_selector/ - 条件选股

**用途**: 根据条件筛选股票

**主要功能**:
- 从股票池中筛选符合条件的股票
- 多维度选股策略
- 批量分析和排序

**使用方式**:
```bash
# (根据实际情况)
python stock_selector/selector.py --条件参数
```

**特点**:
- 条件选股
- 策略筛选
- 批量处理

---

### 3. project/stock/ - 实战项目

**用途**: 实际交易和实战工程

**主要功能**:
- 实盘交易
- 策略回测
- 风险管理

**特点**:
- 生产环境
- 实战应用
- 完整工程

---

## 📋 目录清理建议

### 已完成 ✅

1. **scripts/ → stock_analysis/legacy/**
   - 旧脚本已归档
   - 不再维护

### 建议操作 📝

2. **reports/ → stock_analysis/reports/**
   ```bash
   # 如果 reports/ 下有旧报告
   mv reports/*.md stock_analysis/reports/
   ```

3. **操作手册/ → stock_analysis/docs/**
   ```bash
   # 复制模板文件
   cp 操作手册/stock_analysis_template.md stock_analysis/docs/
   ```

4. **stock/ 目录**
   - 如果不再使用，可以删除或归档
   - 如果有用，保持原样

---

## 🚀 推荐使用方式

### 技术分析
```bash
# 分析单个股票
cd E:\trading
python -m stock_analysis 600519

# 报告保存在
# stock_analysis/reports/600519_YYYYMMDD.md
```

### 条件选股
```bash
# 根据 stock_selector 实际情况使用
cd E:\trading
python stock_selector/selector.py
```

### 实战项目
```bash
# 根据 project/stock 实际情况使用
cd E:\trading/project/stock
python main.py
```

---

## 📖 文档索引

### stock_analysis 文档
- `stock_analysis/README.md` - 完整使用文档
- `stock_analysis/MIGRATION.md` - 旧脚本迁移指南
- `stock_analysis/docs/README.md` - 模板说明
- `stock_analysis/reports/README.md` - 报告说明
- `stock_analysis/legacy/README.md` - 旧脚本说明

### 其他文档
- (根据 stock_selector 和 project 实际情况补充)

---

## 🔧 依赖管理

### stock_analysis 依赖
```bash
cd stock_analysis
pip install -r requirements.txt
```

### 其他模块依赖
根据各模块实际情况安装

---

## 📝 版本控制建议

### .gitignore 设置

```gitignore
# Python
__pycache__/
*.py[cod]
*.so

# 报告和缓存
stock_analysis/reports/*.md
stock_analysis/.cache/
reports/

# 配置文件（如包含敏感信息）
*/config_local.py
*.log

# IDE
.vscode/
.idea/
```

---

## 🎯 下一步计划

1. **stock_analysis**: ✅ 已完成重构
2. **stock_selector**: 📋 待了解和优化
3. **project/stock**: 📋 待了解
4. **目录清理**: 📋 根据建议清理旧目录

---

## ❓ 常见问题

**Q: 三个模块之间有关联吗？**
A: 
- `stock_analysis`: 单股票深度分析
- `stock_selector`: 批量筛选股票
- `project/stock`: 实战应用

可以配合使用：先用 selector 选股，再用 analysis 分析，最后在 project 中实战。

**Q: 旧的 scripts/ 还能用吗？**
A: 旧脚本已废弃并移至 `stock_analysis/legacy/`，建议使用新框架。

**Q: reports/ 目录怎么处理？**
A: 建议将旧报告移至 `stock_analysis/reports/`，统一管理。

---

**当前状态**: stock_analysis 模块已完成重构并归类 ✅
