# PostgreSQL 存储

## 功能

系统会保存两类数据：

- 每次选股批次：日期、策略类别、策略 ID、中文名称、数据源和参数。
- 每只入选股票：代码、名称、价格、涨跌幅、换手率、量比、评分、信号日期和说明。
- 自选股分组：分组名称、股票代码、名称和备注。

## 初始化

先在本机 PostgreSQL 创建数据库：

```sql
CREATE DATABASE stock_selector;
```

在运行程序的 PowerShell 会话中设置连接参数：

```powershell
$env:STOCK_SELECTOR_PGHOST = '127.0.0.1'
$env:STOCK_SELECTOR_PGPORT = '5432'
$env:STOCK_SELECTOR_PGDATABASE = 'stock_selector'
$env:STOCK_SELECTOR_PGUSER = 'postgres'
$env:STOCK_SELECTOR_PGPASSWORD = '你的密码'
```

当前程序默认使用本地 `postgres/root`；设置 `STOCK_SELECTOR_PGPASSWORD` 可覆盖默认密码。

也可以直接设置完整 DSN：

```powershell
$env:STOCK_SELECTOR_PG_DSN = 'host=127.0.0.1 port=5432 dbname=stock_selector user=postgres password=你的密码'
```

安装驱动并初始化表：

```powershell
py -3.11 -m pip install psycopg2-binary
py -3.11 -m stock_selector.data.postgres_store
```

GUI 会自动执行表结构检查。命令行选股和批量选股默认保存数据库；临时跳过可以加 `--no-db`，也可以使用 `--db-dsn` 覆盖连接。

## GUI 自选股分组

GUI 底部的“自选股分组”区域支持：

1. 新建分组；
2. 手动输入代码和名称添加股票；
3. 从选股结果中选择股票后加入分组；
4. 查看当前分组并移除股票。

分组数据直接保存在 PostgreSQL，不依赖 exe 所在目录。

## 策略门槛说明

v2 策略对缺失的成交额字段会跳过成交额过滤。腾讯行情接口没有成交额字段，之前将缺失值当成 0 会导致所有 v2 股票被误筛掉；修复后仍会使用换手率、量比、价格和评分条件。
