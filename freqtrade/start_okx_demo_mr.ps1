# One-click start for the OKX demo mean-reversion bot (5m, long+short).
# Instance 2: API port 8081, own DB/log. Run .\start_okx_demo_mr.ps1 from E:\trading\freqtrade
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$envFile = Join-Path $root ".env.demo"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host "[ERROR] .env.demo not found. Copy .env.demo.example to .env.demo and fill demo keys."
    exit 1
}

Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $name = $line.Substring(0, $idx).Trim()
    $value = $line.Substring($idx + 1).Trim()
    if ($value.Length -ge 2 -and $value.StartsWith([char]34) -and $value.EndsWith([char]34)) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "[ERROR] .venv\Scripts\python.exe not found. Prepare the virtualenv first."
    exit 1
}

foreach ($n in @("FREQTRADE__EXCHANGE__API_KEY", "FREQTRADE__EXCHANGE__SECRET", "FREQTRADE__EXCHANGE__PASSWORD")) {
    $v = [Environment]::GetEnvironmentVariable($n, "Process")
    if ([string]::IsNullOrWhiteSpace($v)) {
        Write-Host "[ERROR] $n is empty. Fill the demo keys in .env.demo first."
        exit 1
    }
}

$listener = Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "[警告] 端口 8081 已被占用 (PID $($listener.OwningProcess))。是否已启动第二实例？"
}

Write-Host "== 预检：OKX 模拟盘签名只读余额请求 =="
& $python (Join-Path $root "demo_guard.py") --local-proxy --preflight `
    --config (Join-Path $root "user_data\config_okx_demo_mr.json") `
    --strategy MeanReversion5mStrategy `
    --db tradesv3-demo-mr.sqlite `
    --logfile freqtrade-demo-mr.log
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 预检失败，启动已阻止。"
    exit $LASTEXITCODE
}

Write-Host "== 预检通过，正在启动 MeanReversion5m 多空策略实例 =="
Write-Host "日志：user_data\logs\freqtrade-demo-mr.log    数据库：user_data\tradesv3-demo-mr.sqlite"
Write-Host "FreqUI：http://127.0.0.1:8081"
Write-Host "停止：按 Ctrl+C 退出本窗口"
& $python (Join-Path $root "demo_guard.py") --local-proxy `
    --config (Join-Path $root "user_data\config_okx_demo_mr.json") `
    --strategy MeanReversion5mStrategy `
    --db tradesv3-demo-mr.sqlite `
    --logfile freqtrade-demo-mr.log
