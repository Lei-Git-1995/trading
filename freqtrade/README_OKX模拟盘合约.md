# OKX 模拟盘：自动开平仓与动态杠杆

更新时间：2026-10-07。目标是先在 OKX 自己的模拟盘运行 1～2 个月，之后再独立审查实盘配置。当前方案为 **USDT 永续合约、逐仓、只做多、BTC/ETH、15m**。

Linux 长期部署、数据记录和备份见 [Linux 部署与数据记录](README_Linux部署与数据记录.md)。

## 关键区别

`user_data/config.json` 是 Freqtrade 本地 Dry-run：不会向交易所发订单。

`user_data/config_okx_demo.json` 是 OKX 模拟盘配置：`dry_run=false`，但所有请求必须带 OKX 官方要求的 `x-simulated-trading: 1`。Freqtrade 2026.9 没有为 OKX 提供内置 `demo_trading` 开关；这里是通过 CCXT 配置和 `demo_guard.py` 预检接入的自定义方案。**在得到模拟盘 API Key 并通过签名只读验证前，不启动自动交易。**

## 已准备文件

- `docker-compose.demo.yml`：独立模拟盘容器；不会使用现货 Dry-run 的 compose 服务。
- `demo_guard.py`：检查模拟盘请求头、合约逐仓、密钥、签名余额请求，失败时阻止启动。
- `.env.demo.example`：密钥模板。复制成 `.env.demo` 后仅在自己的电脑填写，不上传、不发到聊天。
- `user_data/config_okx_demo.json`：模拟盘交易配置，密钥由环境变量注入。
- `user_data/config_okx_futures_backtest.json`：无密钥的合约历史数据/回测配置。
- `user_data/strategies/OKXDemoFuturesStrategy.py`：自动入场、出场与杠杆规则。

## 策略与限制

- EMA12 上穿 EMA26，RSI 在 50～70，成交量有效时产生做多信号。
- EMA 趋势转弱或 RSI 低于 45 时发出平仓信号；同时设置 6% 的杠杆后仓位收益止损和分阶段 ROI 出场。
- 普通信号使用 **3 倍**；只有 RSI 55～65、ADX ≥25、成交量 ≥20 根均量的 1.3 倍、ATR/价格 ≤0.8% 等条件同时满足才使用 **5 倍**。该“强信号”是规则标签，**不是已校准的上涨概率**。
- 若交易所给该交易对的最大杠杆低于目标值，策略自动取交易所上限。
- 最多同时 2 笔，单笔初始保证金 25 USDT；启用冷却、连续止损保护、最大回撤保护和交易所止损。仅做多，不加仓摊平。

模拟盘容器固定为 Freqtrade `2026.9`，避免 1～2 个月观察期内被 `stable` 标签更新改变行为。当前电脑的 Python 直连 OKX DNS 失败，但经本机 HTTP 代理 `127.0.0.1:7897`，REST、公共 WS 和 CCXT Pro 行情均已验证。尚无模拟盘 API Key，因此没有验证签名连接或发送模拟订单；必须在目标电脑完成预检并核对首笔模拟订单。

## REST 与 WebSocket 地址及“实盘”字样

本方案将 CCXT 的 REST 地址固定为 `https://openapi.okx.com`，WS 公共、私有和业务频道固定为 `wss://wspap.okx.com:8443/ws/v5/...`，并为 REST 私有请求添加 `x-simulated-trading: 1`。启动保护会离线校验实际生成的私有 REST 请求头和三个 WS URL。`ws.okx.com` 属于实盘 WS，不能混入此配置。

Freqtrade 显示“实盘交易”或 `dry_run=false`，含义是**由交易所执行订单**；它不能识别这个自定义 OKX Demo 接法的账户标签。只有 Demo 专用密钥、模拟盘请求头、`wspap` WS 地址和签名余额预检都正确，才按本文启动。**不要直接执行 `freqtrade trade --config user_data/config_okx_demo.json` 绕过 `demo_guard.py`。**

## 本机网络检查与代理

本机浏览器/PowerShell 能访问 OKX，但 Python/CCXT 不自动继承 Windows 代理。已验证下面的命令能读到 REST 时间、模拟盘公共 WS 行情和 CCXT Pro 行情：

```powershell
cd E:\trading\freqtrade
.\.venv\Scripts\python.exe network_probe.py --proxy http://127.0.0.1:7897 --ccxt-pro
```

在当前 Windows 电脑下载数据、回测时，在基础配置后追加 `--config user_data/config_proxy_local.example.json`；它只增加 `httpsProxy` 和 `wssProxy`，不改变 Demo 地址和密钥。当前电脑若将来填入 Demo 密钥，先运行 `.\.venv\Scripts\python.exe demo_guard.py --local-proxy --preflight`，通过后才可运行 `.\.venv\Scripts\python.exe demo_guard.py --local-proxy`。另一台 Docker 电脑若可直接访问 OKX，不使用这个本机代理覆盖配置。

## 已完成的历史基线回测

2026-10-07 使用 BTC/ETH 永续约 60 天的公开数据，15m、逐仓、含 Freqtrade 估算手续费运行当前策略：205 笔，净收益 **-10.071 USDT（-1.01%）**，胜率 35.1%，最大回撤 11.259 USDT（1.13%）。`base_3x` 199 笔净亏 11.493 USDT；`strong_5x` 仅 6 笔净赚 1.422 USDT。**总体表现为负，5 倍组样本过少，不能据此推断更高胜率。**这份策略应只作为模拟盘观察基线，不能直接进入真钱环境。
## 在另一台 Docker 电脑上部署

### 1. 复制项目

复制整个 `freqtrade-transfer.zip` 到另一台电脑并解压。不要复制 `.venv`。进入解压目录：

```powershell
cd E:\trading\freqtrade
```

### 2. 获取 OKX 模拟盘 API

在 OKX 的模拟交易页面创建**模拟盘专用** API Key、Secret 和 Passphrase。账户应启用 USDT 永续合约，并把持仓模式设为单向持仓（net mode）。API 权限只给读取和交易，不给提现；如可用，设置目标电脑公网 IP 白名单。不要使用实盘 API Key。

把 `.env.demo.example` 复制为 `.env.demo`，然后在本机填写：

```dotenv
FREQTRADE__EXCHANGE__API_KEY=你的模拟盘APIKey
FREQTRADE__EXCHANGE__SECRET=你的模拟盘Secret
FREQTRADE__EXCHANGE__PASSWORD=你的模拟盘Passphrase
```

`.env.demo` 已加入 `.gitignore`，不会放入迁移包。不要把密钥写进策略文件或提交到 Git。

### 3. 拉取镜像并做静态检查

```powershell
docker compose -f docker-compose.demo.yml pull
docker compose -f docker-compose.demo.yml run --rm freqtrade-demo --check-config
```

### 4. 下载合约历史数据并回测

```powershell
docker compose run --rm freqtrade download-data `
  --config user_data/config_okx_futures_backtest.json `
  --pairs BTC/USDT:USDT ETH/USDT:USDT `
  --days 60 `
  -t 15m `
  --trading-mode futures

docker compose run --rm freqtrade backtesting `
  --config user_data/config_okx_futures_backtest.json `
  --strategy OKXDemoFuturesStrategy `
  -i 15m
```

回测需要足够历史 K 线和合约资金费率数据。网络或地区限制可能导致下载失败；不要用缺失数据产生的结果判断策略表现。

### 5. 签名只读模拟盘预检

```powershell
docker compose -f docker-compose.demo.yml run --rm freqtrade-demo --preflight
```

只有看到 `Authenticated signed OKX Demo balance request passed.`，才进入下一步。此预检读取模拟盘余额，不会下单。若失败，先检查 API Key、Passphrase、IP 白名单、账户模式和网络；**不要绕开预检或删除模拟盘请求头**。

### 6. 启动自动模拟交易

```powershell
docker compose -f docker-compose.demo.yml up -d
docker compose -f docker-compose.demo.yml logs -f --tail=100
```

守护脚本会再次做模拟盘签名请求，成功后启动 Freqtrade。订单、持仓、止损与杠杆应在 OKX 模拟盘中核对。策略需要出现入场信号才会下单，启动成功不代表立即有订单。

停止：

```powershell
docker compose -f docker-compose.demo.yml down
```

请不要同时启动现货 Dry-run 的 `docker-compose.yml` 与这个模拟盘服务，以免混淆日志、资金和策略表现。

## 1～2 个月观察记录

每天核对：容器存活、日志错误、每笔模拟订单和持仓的杠杆、交易所止损是否存在、API 是否被限流。每周可在宿主机运行 `python demo_report.py --days 7 --starting-equity <模拟盘初始权益>`，或使用当前 `.venv\Scripts\python.exe demo_report.py --days 7`，报告写入 `user_data/reports/`。每周导出交易记录，分别统计 3 倍与 5 倍信号的交易数、净收益、最大回撤、止损率、资金费率、滑点以及无法成交的订单。至少跨越不同波动环境，再评估 5 倍是否有增益；不要仅看总收益。

进入实盘前应新建独立的实盘配置和数据库，重新审查最大持仓、单笔风险、交易所止损、断线恢复与应急停机。**不要通过删除 `x-simulated-trading` 请求头或直接修改本模拟盘配置来切实盘。**

## 无 Docker 的当前 Windows 电脑

当前电脑已有 `.venv`。在 PowerShell 中可做静态检查：

```powershell
cd E:\trading\freqtrade
.\.venv\Scripts\python.exe demo_guard.py --check-config
```

填写模拟盘密钥到当前 PowerShell 会话的环境变量后，再运行：

```powershell
.\.venv\Scripts\python.exe demo_guard.py --preflight
.\.venv\Scripts\python.exe demo_guard.py
```

推荐在另一台长期在线的电脑执行 1～2 个月监测；当前电脑可负责修改策略、回测和复盘。

## 官方依据

- OKX 模拟盘请求头与 API 创建：https://www.okx.com/docs-v5/en/#overview-demo-trading-services
- OKX 杠杆接口：https://www.okx.com/docs-v5/en/#rest-api-account-set-leverage
- Freqtrade OKX 支持范围：https://www.freqtrade.io/en/stable/exchanges/#okx
- Freqtrade 合约与杠杆：https://www.freqtrade.io/en/stable/leverage/
- Freqtrade 策略杠杆回调：https://www.freqtrade.io/en/stable/strategy-callbacks/#leverage-callback






