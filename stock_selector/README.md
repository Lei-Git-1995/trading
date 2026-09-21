# 股票选股系统

短线选股系统，支持多数据源、多策略、智能筛选。

## 快速开始

### 基础使用
```bash
cd E:\trading
py -3.11 -m stock_selector.main
```

### 查看所有预设策略
```bash
py -3.11 -m stock_selector.main --list-presets
```

### 使用预设策略
```bash
# 激进策略（追涨）
py -3.11 -m stock_selector.main --preset aggressive

# 保守策略（稳健）
py -3.11 -m stock_selector.main --preset conservative

# 只选主板股票
py -3.11 -m stock_selector.main --mainboard-only
```

## 📚 完整文档

所有详细文档请查看：**[docs 目录](docs/README.md)**

- [命令使用大全](docs/命令使用大全.md) - 最全面的命令参考
- [快速开始指南](docs/QUICK_START.md) - 5分钟快速上手
- [主板过滤功能](docs/MAINBOARD_FILTER.md) - 只选主板股票
- [优化功能说明](docs/OPTIMIZATION.md) - 新功能详解

## 核心功能

✅ **6个预设策略** - 一键切换不同选股风格  
✅ **多数据源支持** - 东方财富/腾讯/新浪  
✅ **智能筛选** - 换手率/涨跌幅/量能/技术指标  
✅ **进度显示** - 实时进度条，不再焦虑等待  
✅ **性能统计** - 各阶段耗时一目了然  
✅ **日志系统** - 彩色输出 + 文件记录  
✅ **主板模式** - 一键过滤创业板/科创板  

## 预设策略

| 策略 | 命令 | 适用场景 |
|------|------|---------|
| 默认 | `--preset default` | 日常选股 |
| 激进 | `--preset aggressive` | 追涨强势股 |
| 保守 | `--preset conservative` | 稳健投资 |
| 低吸 | `--preset dip_buying` | 寻找反弹 |
| 突破 | `--preset breakout` | 放量突破 |
| 主板 | `--preset mainboard_only` | 只选主板 |

## 输出文件

- **选股报告**：`output/YYYY-MM-DD.md`
- **日志文件**：`logs/YYYY-MM-DD.log`

## 依赖安装

```bash
pip install pandas numpy requests akshare pyyaml tqdm colorama
```

## 项目结构

```
stock_selector/
├── main.py              # 程序入口
├── config.py            # 配置管理
├── presets.yaml         # 预设策略
├── data/                # 数据层
├── indicators/          # 技术指标
├── strategies/          # 选股策略
├── reports/             # 报告生成
├── utils/               # 工具模块
│   ├── logger.py        # 日志系统
│   ├── config_loader.py # 配置加载
│   └── timer.py         # 性能统计
├── docs/                # 📚 完整文档
├── output/              # 选股报告
└── logs/                # 日志文件
```

## 常用命令

```bash
# 查看帮助
py -3.11 -m stock_selector.main --help

# 查看所有预设
py -3.11 -m stock_selector.main --list-presets

# 自定义参数
py -3.11 -m stock_selector.main --turnover 12 --change 1,5 --volume 1.8

# 只选主板
py -3.11 -m stock_selector.main --mainboard-only

# 不使用缓存（最新数据）
py -3.11 -m stock_selector.main --no-cache

# 交互式输入
py -3.11 -m stock_selector.main -i

# 调试模式
py -3.11 -m stock_selector.main --log-level DEBUG
```

## 更多文档

详细使用说明请查看 **[docs/README.md](docs/README.md)**

---

**祝您选股顺利！📈**
