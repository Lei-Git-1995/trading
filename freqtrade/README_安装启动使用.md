## OKX 模拟盘自动下单

如需在 OKX 模拟盘真实创建模拟订单、自动开平仓并使用 3/5 倍动态杠杆，请先阅读 [OKX 模拟盘合约指南](README_OKX模拟盘合约.md)。原文档中的 dry_run=true 仅为 Freqtrade 本地模拟，两者为独立配置。

# Freqtrade 安装、迁移与使用

更新时间：2026-10-07。当前模板以 Freqtrade 2026.9、OKX 现货、BTC/USDT 与 ETH/USDT、15 分钟 K 线为例。

## 1. 已准备的文件

```text
freqtrade/
├── docker-compose.yml             # 给另一台已安装 Docker 的电脑使用
├── .gitignore                     # 避免提交密钥、行情、交易数据库
├── .venv/                         # 当前 Windows 电脑的 Python 环境，不要复制到另一台电脑
└── user_data/
    ├── config.json                # 安全默认配置，dry_run=true、密钥为空
    ├── OKX_DEMO_KEYS.example.json # 仅作字段提示，非可直接运行的配置
    ├── strategies/
    │   └── EMAStartStrategy.py    # EMA 交叉学习策略
    ├── data/okx/                  # 下载历史行情后生成数据文件
    ├── logs/                      # 启动后生成日志
    └── notebooks/
```

`tradesv3.sqlite` 会在运行后生成，无需提前创建。

## 2. 模式说明

- **回测**：使用下载的历史 K 线，不发真实订单。
- **Dry-run**：读取实时行情，在本地模拟订单，不向 OKX 发真实订单。当前 `config.json` 已设置 `dry_run=true`，API Key 留空即可先学习和测试。
- **OKX Demo**：OKX 交易所自己的模拟盘，与 Freqtrade Dry-run 不同。Freqtrade 2026.9 的官方 OKX 文档没有提供内置 Demo 开关。项目另备有自定义 Demo REST/WS 配置与启动保护，详见 `README_OKX模拟盘合约.md`；基础 `config.json` 仍是独立的本地 Dry-run。
- **实盘**：当前模板未启用。不要仅把 `dry_run` 改成 `false` 就直接运行。

## 3. 在另一台已有 Docker 的电脑运行

### 3.1 复制文件

把 `docker-compose.yml`、`.gitignore` 和整个 `user_data/` 复制到另一台电脑，例如 `E:\trading\freqtrade`。不要复制 `.venv/`。不要在传输前填入真实密钥。

Docker Desktop 启动并显示引擎可用后，在 PowerShell 中执行：

```powershell
cd E:\trading\freqtrade
docker compose version
docker compose pull
```

`user_data/` 已存在，因此**不要再次执行 `create-userdir` 或 `new-config`**，否则可能覆盖已准备的目录与配置。

### 3.2 验证配置和策略

```powershell
docker compose run --rm freqtrade show-config --config user_data/config.json
docker compose run --rm freqtrade list-strategies --config user_data/config.json
```

`list-strategies` 中 `EMAStartStrategy` 应显示 `OK`。`show-config` 会遮蔽密钥，但仍不要把完整输出随意发给别人。

### 3.3 下载 30 天数据

```powershell
docker compose run --rm freqtrade download-data `
  --config user_data/config.json `
  --exchange okx `
  --pairs BTC/USDT ETH/USDT `
  --days 30 `
  -t 15m
```

数据会写入 `user_data/data/okx/`。下载依赖另一台电脑能访问 OKX 行情接口；如果地区或网络限制导致失败，先检查网络，不要凭空生成行情文件。

### 3.4 回测

```powershell
docker compose run --rm freqtrade backtesting `
  --config user_data/config.json `
  --strategy EMAStartStrategy `
  -i 15m
```

当前策略只是 EMA 交叉学习示例，尚未通过多阶段验证。记录交易笔数、净收益、最大回撤和不同时间段表现。仅 30 天数据适合验证流程，不足以判断策略长期有效性。

### 3.5 Dry-run

先确认 `user_data/config.json` 中仍为 `"dry_run": true`，然后执行：

```powershell
docker compose up -d
docker compose logs -f --tail=100
```

停止：

```powershell
docker compose down
```

`docker-compose.yml` 默认启动 `EMAStartStrategy`。FreqUI/API 默认关闭，因此浏览器访问 `localhost:8080` 不会出现界面。先通过日志验证 Dry-run；之后如需界面，再设置强密码、随机 JWT/WS 密钥并开启 `api_server.enabled`。不要把 8080 端口暴露给公网。

## 4. 在当前 Windows 电脑不用 Docker 运行

当前电脑已安装到 `E:\trading\freqtrade\.venv`，版本为 Freqtrade 2026.9。PowerShell 命令：

```powershell
cd E:\trading\freqtrade
.\.venv\Scripts\freqtrade.exe --version
.\.venv\Scripts\freqtrade.exe list-strategies --config user_data\config.json
```

下载行情：

```powershell
.\.venv\Scripts\freqtrade.exe download-data `
  --config user_data\config.json `
  --exchange okx `
  --pairs BTC/USDT ETH/USDT `
  --days 30 `
  -t 15m
```

回测：

```powershell
.\.venv\Scripts\freqtrade.exe backtesting `
  --config user_data\config.json `
  --strategy EMAStartStrategy `
  -i 15m
```

Dry-run（保持 PowerShell 窗口开启）：

```powershell
.\.venv\Scripts\freqtrade.exe trade `
  --config user_data\config.json `
  --strategy EMAStartStrategy
```

按 `Ctrl+C` 停止。另一台电脑若不用 Docker，需重新创建自己的虚拟环境并安装 Freqtrade，不能直接复制这里的 `.venv`。

## 5. 配置字段怎么改

编辑 `user_data/config.json`：

| 字段 | 当前值 | 含义 |
|---|---:|---|
| `dry_run` | `true` | 仅本地模拟订单 |
| `exchange.name` | `okx` | OKX 现货行情 |
| `exchange.pair_whitelist` | BTC、ETH | 允许交易的交易对 |
| `stake_currency` | `USDT` | 计价币种 |
| `stake_amount` | `100` | 每笔模拟投入 100 USDT |
| `dry_run_wallet` | `1000` | 初始模拟资金 1000 USDT |
| `max_open_trades` | `3` | 最多同时持有 3 笔 |
| `timeframe` | `15m` | K 线周期 |
| `api_server.enabled` | `false` | 默认不开放 FreqUI/API |

策略中的 `stoploss=-0.05` 是 5% 止损，`minimal_roi` 是分阶段获利门槛。修改策略后应重新回测和 Dry-run。

`exchange.api_key`、`secret`、`password` 目前全部为空。OKX 的 `password` 是 API Passphrase，不是登录密码。不要在聊天、Git 仓库或截图中公开密钥。用于 Freqtrade Dry-run 时通常无需填写真实交易密钥。

## 6. 资源与迁移建议

当前电脑是 i5-12400（6 核 12 线程）、32GB RAM、E 盘剩余约 230GB。Freqtrade Python 虚拟环境约 0.55GB。运行 1 个 15m 策略、2 个交易对，通常不需要独立显卡；当前机器做配置、下载数据和单策略回测足够。另一台电脑建议至少 4 核 CPU、8GB RAM、20GB 可用磁盘；若与其他服务共用，16GB RAM 更宽裕。大量交易对、长周期细粒度数据、Hyperopt 或 FreqAI 的资源消耗会明显增加。

复制到另一台电脑时只需 `docker-compose.yml` 和 `user_data/`；`data/okx/` 可选择复制，也可以在目标电脑重新下载。数据库和日志可按需保留，不应混用测试与实盘数据库。

## 7. 官方参考

- 安装：https://www.freqtrade.io/en/stable/installation/
- Docker 快速开始：https://www.freqtrade.io/en/stable/docker_quickstart/
- 配置：https://www.freqtrade.io/en/stable/configuration/
- 策略入门：https://www.freqtrade.io/en/stable/strategy-customization/
- OKX 交易所说明：https://www.freqtrade.io/en/stable/exchanges/#okx
- 回测：https://www.freqtrade.io/en/stable/backtesting/



