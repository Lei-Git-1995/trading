# Linux 部署与数据记录

更新时间：2026-10-07。以下按 **Ubuntu/Debian + Docker Compose** 写；其他 Linux 发行版的 Docker 安装命令不同，但项目文件和 Compose 用法相同。此方案在 Linux 上尚未实际启动容器，已在当前 Windows 环境验证配置、REST/WS 连通性、行情 SQLite 落盘和备份。

## 1. 资源与存储

建议服务器至少 2 vCPU、4 GB RAM、20 GB 可用磁盘；与其他服务共用时建议 4 vCPU、8 GB RAM。这是当前 **2 个交易对、15m、1 个策略和 1 个行情记录器**的部署估算，不是 Freqtrade 的硬性门槛。无需 GPU。

所有需要保留的数据位于宿主机项目目录，而不是容器内部：

```text
/opt/freqtrade/
├── docker-compose.demo.yml       # 模拟盘自动交易服务
├── docker-compose.recorder.yml   # 独立公开行情记录服务
├── .env.demo                     # 目标机器本地填写；不包含在迁移包/备份中
├── backups/                      # 每日备份归档
└── user_data/
    ├── tradesv3-demo.sqlite      # Freqtrade 模拟盘交易、订单、持仓状态
    ├── market_data.sqlite        # BTC/ETH 已收盘 15m K 线
    ├── data/okx/                 # Freqtrade 回测历史数据
    ├── logs/                     # 交易与行情记录日志
    ├── reports/                  # 每周交易复盘
    └── strategies/               # 策略源代码
```

两个 Compose 服务均把 `./user_data` 映射到 `/freqtrade/user_data`。容器更新、停止或重建不会删除宿主机的 SQLite、行情文件和日志。**不要对正在写入的 SQLite 数据库直接 `cp` 作为备份**；使用下方的在线备份脚本。

`market_data.sqlite` 只保存确认收盘的 15m OHLCV K 线，主键是交易对、周期和时间戳，不保存逐笔成交、全量盘口或未收盘 K 线。交易订单与收益保存在 Freqtrade 的 `tradesv3-demo.sqlite`。记录器断线后会重连，并通过 REST 补录缺失区间、复核最近 1 天数据。

## 2. 安装 Docker 并复制项目

按 [Docker 官方 Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/) 安装 Docker Engine 与 Compose 插件。确认：

```bash
docker --version
docker compose version
docker info
```

安装 `unzip` 与 Python 3（备份脚本只依赖 Python 标准库），将 [freqtrade-transfer.zip](freqtrade-transfer.zip) 复制到服务器后。迁移包只含代码、配置模板和公开历史行情，**不含运行期 SQLite、日志或密钥**；若需迁移已有记录，另复制 `backups/` 中的备份归档并按恢复章节操作：

```bash
sudo mkdir -p /opt/freqtrade
sudo chown "$USER":"$USER" /opt/freqtrade
cd /opt/freqtrade
unzip freqtrade-transfer.zip
mkdir -p user_data/logs user_data/reports backups
```

确认容器对 `user_data` 有写入权限。若出现 `Permission denied`，查看容器运行 UID，再把 `user_data` 归属调整为该 UID；不要对项目目录直接使用 `chmod 777`。检查系统时钟：

```bash
timedatectl status
```

OKX API 签名对时间敏感，系统应启用自动时间同步。

## 3. 先启动公开行情记录器（不需要 API Key）

先验证 REST 和 WS 网络：

```bash
cd /opt/freqtrade
docker compose -f docker-compose.recorder.yml pull
docker compose -f docker-compose.recorder.yml run --rm \
  --entrypoint python okx-market-recorder /freqtrade/network_probe.py --ccxt-pro
```

成功时应看到 `REST OK`、`WS OK`、`Business WS OK`、`CCXT Pro OK`。如果 Linux 宿主机需要本地 HTTP 代理，可在运行 Compose 前设置 `OKX_PROXY_URL=http://host.docker.internal:代理端口`；记录器 Compose 已配置宿主机网关映射。此环境变量仅作用于公开行情记录器。交易服务若也需要代理，需另行配置并通过 Demo 签名预检；不能假设记录器连通就代表私有下单接口连通。代理必须由你控制，因为私有请求可能经过它。

先做一次 REST 补录，再启动 WS 常驻记录：

```bash
docker compose -f docker-compose.recorder.yml run --rm \
  okx-market-recorder --once --initial-days 7
docker compose -f docker-compose.recorder.yml up -d
docker compose -f docker-compose.recorder.yml logs -f --tail=100
```

另开终端检查落盘数量、最新时间和缺口：

```bash
cd /opt/freqtrade
docker compose -f docker-compose.recorder.yml run --rm okx-market-recorder --status
```

`missing_intervals=0` 且 `lag_minutes` 大致小于 30 分钟，说明记录持续跟上最新 15m K 线。Compose 每 5 分钟做一次只读健康检查；最新 K 线滞后超过 45 分钟时，`docker compose -f docker-compose.recorder.yml ps` 会显示 `unhealthy`。Docker 不会仅因 unhealthy 自动重启容器，应接入目标服务器的监控/告警并检查日志。网络中断后记录器会重连并通过 REST 补录；如果最新时间长期不更新，先看容器日志。

## 4. 回测与模拟盘自动交易

行情记录器独立运行，不会下单。自动模拟交易使用另一个 Compose 文件。先下载回测数据并验证策略：

```bash
docker compose run --rm freqtrade download-data \
  --config user_data/config_okx_futures_backtest.json \
  --pairs BTC/USDT:USDT ETH/USDT:USDT \
  --days 60 -t 15m --trading-mode futures

docker compose run --rm freqtrade backtesting \
  --config user_data/config_okx_futures_backtest.json \
  --strategy OKXDemoFuturesStrategy -i 15m
```

当前策略的约 60 天基线回测为 205 笔、总收益 -1.01%、胜率 35.1%。这只是模拟盘观察基线，不能作为实盘依据。

在 OKX 模拟盘创建专用 API Key 后，**只在 Linux 服务器本地**填写密钥：

```bash
cp .env.demo.example .env.demo
chmod 600 .env.demo
# 使用本机文本编辑器填写 API_KEY、SECRET、PASSWORD（Passphrase）
```

预检使用签名只读余额请求，不下单：

```bash
docker compose -f docker-compose.demo.yml pull
docker compose -f docker-compose.demo.yml run --rm freqtrade-demo --check-config
docker compose -f docker-compose.demo.yml run --rm freqtrade-demo --preflight
```

看到 `Authenticated signed OKX Demo balance request passed.` 后，再启动：

```bash
docker compose -f docker-compose.demo.yml up -d
docker compose -f docker-compose.demo.yml logs -f --tail=100
```

Freqtrade 会显示 `dry_run=false` 或“实盘交易”，因为订单由**交易所**处理；这里必须同时确认配置只指向 `openapi.okx.com`、`wspap.okx.com`，私有 REST 带 `x-simulated-trading: 1`，且 OKX 模拟盘页面能看到订单。此 OKX Demo 接法是自定义集成，尚未用你的 Demo 密钥完成签名连接与首笔模拟订单验证。**不要绕过 `demo_guard.py` 直接启动 Freqtrade。**

## 5. 记录、周报和备份

每周在宿主机生成按 3 倍和 5 倍信号分组的交易报告：

```bash
cd /opt/freqtrade
python3 demo_report.py --days 7 --starting-equity 1000
```

报告写入 `user_data/reports/`。交易库中尚无订单时，报告显示 0 笔。每天核对 OKX 模拟盘网页的订单、杠杆、止损及 Freqtrade 数据库记录是否一致。

手动执行一次一致性备份：

```bash
cd /opt/freqtrade
python3 backup_data.py --keep-days 30
ls -lh backups/
```

备份脚本用 SQLite 的在线备份 API 快照 `tradesv3-demo.sqlite` 和 `market_data.sqlite`，并归档配置、策略及当前日志；不包含 `.env.demo`，配置中的 API/Telegram/Web UI 密钥字段会清空；日志可能含敏感信息，向外部传送备份前应检查。归档默认保留 30 天。可以在宿主机 `crontab -e` 中加一行，每天 03:00 备份：

```cron
0 3 * * * cd /opt/freqtrade && /usr/bin/python3 backup_data.py --keep-days 30 >> /opt/freqtrade/user_data/logs/backup.log 2>&1
```

建议把 `backups/` 再同步到另一块磁盘或远端对象存储，避免服务器磁盘故障同时丢失原始数据和备份。`.env.demo` 单独安全保管，不随普通备份同步。

## 6. 查看服务、停止和恢复

```bash
cd /opt/freqtrade
docker compose -f docker-compose.recorder.yml ps
docker compose -f docker-compose.demo.yml ps
docker compose -f docker-compose.recorder.yml logs --tail=100
docker compose -f docker-compose.demo.yml logs --tail=100
```

停止服务不会删除宿主机数据：

```bash
docker compose -f docker-compose.demo.yml down
docker compose -f docker-compose.recorder.yml down
```

恢复归档前先停两个服务，另外保存当前数据，再把可信备份解压到同一项目目录：

```bash
cd /opt/freqtrade
docker compose -f docker-compose.demo.yml down
docker compose -f docker-compose.recorder.yml down
python3 backup_data.py --keep-days 30
tar -xzf backups/okx-demo-YYYYMMDDTHHMMSSZ.tar.gz -C /opt/freqtrade
docker compose -f docker-compose.recorder.yml up -d
# 重新完成 Demo API 预检后再启动交易服务
```

`tradesv3-demo.sqlite` 是模拟盘交易状态，恢复旧快照后必须先核对 OKX 模拟盘当前真实持仓和未完成订单；不能仅凭旧数据库直接恢复自动下单。

## 官方参考

- [Docker Engine Ubuntu 安装](https://docs.docker.com/engine/install/ubuntu/)
- [Docker Compose Linux 安装](https://docs.docker.com/compose/install/linux/)
- [Freqtrade Docker 快速开始](https://www.freqtrade.io/en/stable/docker_quickstart/)
- [OKX 模拟盘与 WS 接口](https://www.okx.com/docs-v5/en/#overview-demo-trading-services)
## 8. systemd 自启动与每日备份

迁移包提供 4 个 systemd 模板。确认目录已经放在 `/opt/freqtrade` 后执行：

```bash
sudo install -m 0644 systemd/okx-market-recorder.service /etc/systemd/system/
sudo install -m 0644 systemd/freqtrade-okx-demo.service /etc/systemd/system/
sudo install -m 0644 systemd/okx-freqtrade-backup.service /etc/systemd/system/
sudo install -m 0644 systemd/okx-freqtrade-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now okx-market-recorder.service
sudo systemctl enable --now okx-freqtrade-backup.timer
```

先不要启用 `freqtrade-okx-demo.service`。完成 `.env.demo`、Docker 镜像、模拟盘签名预检和首笔订单核对后再执行：

```bash
sudo systemctl enable --now freqtrade-okx-demo.service
sudo systemctl status okx-market-recorder.service freqtrade-okx-demo.service okx-freqtrade-backup.timer
```

查看 systemd 日志：

```bash
sudo journalctl -u okx-market-recorder.service -f
sudo journalctl -u freqtrade-okx-demo.service -f
sudo journalctl -u okx-freqtrade-backup.service --since today
```

Docker 容器本身也设置了 `restart: unless-stopped`；systemd 和 Docker 双层恢复时只保留一份 Compose 管理入口，不要同时手动 `docker compose up` 和 `systemctl start`。

