# OKX 模拟盘一键启动（使用本地 .venv + 代理 127.0.0.1:7897）
# 用法：在 E:\trading\freqtrade 下运行 .\start_okx_demo.ps1
# 前置条件：先在 .env.demo 中填写 OKX 模拟盘的 API Key / Secret / Passphrase。
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$envFile = Join-Path $root ".env.demo"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host "[错误] 未找到 .env.demo。请将 .env.demo.example 复制为 .env.demo 并填写模拟盘密钥。"
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
    Write-Host "[错误] 未找到 .venv\Scripts\python.exe。请先准备虚拟环境。"
    exit 1
}

foreach ($n in @("FREQTRADE__EXCHANGE__API_KEY", "FREQTRADE__EXCHANGE__SECRET", "FREQTRADE__EXCHANGE__PASSWORD")) {
    $v = [Environment]::GetEnvironmentVariable($n, "Process")
    if ([string]::IsNullOrWhiteSpace($v)) {
        Write-Host "[错误] $n 为空。请先在 .env.demo 中填写模拟盘密钥。"
        exit 1
    }
}

Write-Host "== 预检：OKX 模拟盘签名只读余额请求 =="
& $python (Join-Path $root "demo_guard.py") --local-proxy --preflight
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 预检失败，启动已阻止。请检查 API 密钥、密码/口令、账号模式或代理设置。"
    exit $LASTEXITCODE
}

Write-Host "== 预检通过，正在启动 OKX 模拟盘自动交易 =="
Write-Host "日志：user_data\logs\freqtrade-demo.log    数据库：user_data\tradesv3-demo.sqlite"
Write-Host "停止：按 Ctrl+C 退出本窗口"
& $python (Join-Path $root "demo_guard.py") --local-proxy
