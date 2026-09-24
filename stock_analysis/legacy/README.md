# 旧版脚本（已废弃）

本目录包含重构前的旧版独立脚本，已被统一框架替代。

**⚠️ 这些脚本已不再维护，仅供参考和备份。**

## 脚本列表

| 文件 | 功能 | 状态 | 替代方案 |
|------|------|------|---------|
| `csv_stock_analyzer.py` | CSV数据分析 | ❌ 已废弃 | `python -m stock_analysis --csv` |
| `eastmoney_stock_analyzer.py` | 东方财富数据源 | ❌ 已废弃 | `python -m stock_analysis` (自动选择) |
| `sina_stock_analyzer.py` | 新浪财经数据源 | ❌ 已废弃 | 接口不稳定，建议用新框架 |
| `stock_analyzer.py` | 多主机容灾版 | ❌ 已废弃 | 已整合到新框架 |
| `stock_analyzer_akshare.py` | AkShare数据源 | ❌ 已废弃 | `python -m stock_analysis --source akshare` |

## 为什么废弃？

1. **代码重复严重**: 70%的代码在5个脚本中重复
2. **维护成本高**: 修改一个功能需要在5个地方同步
3. **缺乏统一接口**: 每个脚本使用方式不同
4. **容错能力弱**: 只有1个脚本支持容灾降级
5. **无数据验证**: 缺少数据质量检查

## 迁移到新框架

### 旧命令 → 新命令

```bash
# 旧：东方财富
python scripts/eastmoney_stock_analyzer.py 600519
# 新：自动选择最优数据源
python -m stock_analysis 600519

# 旧：CSV分析
python scripts/csv_stock_analyzer.py data.csv
# 新：CSV分析
python -m stock_analysis --csv data.csv --code 600519

# 旧：新浪财经
python scripts/sina_stock_analyzer.py 600519
# 新：建议使用自动选择（新浪接口不稳定）
python -m stock_analysis 600519
```

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

## 完整迁移指南

参见: `../MIGRATION.md`

## 需要帮助？

查看父目录的文档：
- `../README.md` - 完整使用文档
- `../MIGRATION.md` - 迁移指南
- `../QUICKSTART.md` - 快速开始
- `../REFACTORING_SUMMARY.md` - 重构总结
