# 股票选股系统

`stock_selector` 是一个面向沪深 A 股的短线选股系统，支持多数据源、预设策略、技术指标筛选、v2 多维度评分和 Markdown 报告输出。

## 目录结构

```text
stock_selector/
├── main.py                    # 常规选股入口
├── strategy_runner.py         # 技术形态选股入口
├── daily_batch_runner.py      # 多策略批量选股入口
├── gui_app.py                 # 桌面 GUI
├── build_gui.ps1              # Windows GUI 打包脚本
├── backtest_runner.py         # 回测入口
├── config.py                  # 全局配置和筛选参数
├── presets*.yaml              # 策略预设
├── data/                      # 数据源、缓存和行情标准化
├── indicators/                # 技术指标和形态识别
├── strategies/                # 常规、v2 和技术形态策略
├── backtest/                  # 回测逻辑
├── reports/                   # Markdown/Excel 报告生成
├── data/postgres_store.py    # PostgreSQL 选股记录和自选股分组
├── notification/              # 通知功能
├── utils/                     # 日志、配置加载和工具
├── docs/                      # 使用、架构和维护文档
├── test_*.py                  # 离线测试
├── output/                    # 运行生成的报告
└── logs/                      # 运行生成的日志
```

运行缓存位于 `data/.cache/`。GUI 打包后输出到仓库根目录的 `dist/StockSelector/`；分发时请复制整个文件夹，包含 exe、`_internal/`、`data/` 和两个预设 YAML 文件。

打包入口和配置 `E:\trading\run_gui.py`、`E:\trading\StockSelector.spec` 放在仓库根目录，由 `build_gui.ps1` 调用；前者负责启动 GUI，后者定义 PyInstaller 的打包内容。

## 快速开始

```powershell
cd E:\trading
py -3.11 -m stock_selector.main --list-presets
py -3.11 -m stock_selector.main --preset conservative
```

技术形态选股：

```powershell
py -3.11 -m stock_selector.strategy_runner --list-strategies
py -3.11 -m stock_selector.strategy_runner --strategy ma_trend --limit 100
```

常规选股如需同时生成 Excel 报告：

```powershell
py -3.11 -m stock_selector.main --preset conservative --excel
```

## Windows 图形界面

源码运行：

```powershell
py -3.11 -m stock_selector.gui_app
```

打包为独立程序（需要 Python 3.11；脚本会在缺少时安装 PyInstaller）：

```powershell
powershell -ExecutionPolicy Bypass -File E:\trading\stock_selector\build_gui.ps1
```

打包结果在 `E:\trading\dist\StockSelector\StockSelector.exe`。将整个 `StockSelector` 文件夹一起分发；预设文件可在 exe 旁编辑。

历史技术策略回测（输入为标准化日线 CSV，列名使用项目约定的中文字段）：

```powershell
py -3.11 -m stock_selector.backtest_runner `
  --input data\sample_history.csv `
  --strategy sideways_then_up_3 `
  --holding-days 1
```

技术形态检测 API 位于 `stock_selector.indicators.pattern_recognition`，支持双底、双顶、头肩顶、三角形和矩形整理。通用机器人通知可通过 `--notify-webhook URL` 启用；Webhook 地址由用户自行提供。

完整使用说明请查看 [文档目录](docs/文档目录.md)。

## PostgreSQL 数据库

程序可将每次选股结果和自选股分组保存到本地 PostgreSQL。先创建数据库：

默认连接 `127.0.0.1:5432` 上的 `stock_selector` 数据库，用户名 `postgres`、密码 `root`。也可设置下面环境变量覆盖连接参数：

```sql
CREATE DATABASE stock_selector;
```

然后设置连接信息（密码不写入项目文件）：

```powershell
$env:STOCK_SELECTOR_PGHOST = '127.0.0.1'
$env:STOCK_SELECTOR_PGPORT = '5432'
$env:STOCK_SELECTOR_PGDATABASE = 'stock_selector'
$env:STOCK_SELECTOR_PGUSER = 'postgres'
$env:STOCK_SELECTOR_PGPASSWORD = '你的密码'
```

安装驱动并初始化表结构：

```powershell
py -3.11 -m pip install psycopg2-binary
py -3.11 -m stock_selector.data.postgres_store
```

GUI 启动后会自动检查并创建表；选股完成时会保存策略、日期、数据源、评分、指标和入选说明。数据库暂时不可用时，原有选股和报告仍可正常运行。
