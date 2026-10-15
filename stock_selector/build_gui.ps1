# Build the GUI stock selector into a standalone Windows executable.
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File E:\trading\stock_selector\build_gui.ps1
# Optional output root lets a new build finish while an older exe is running.
param(
    [string]$OutputRoot = 'E:\trading\dist',
    [string]$WorkRoot = ''
)

$ErrorActionPreference = 'Stop'

$root = 'E:\trading'
$spec = Join-Path $root 'StockSelector.spec'
$name = 'StockSelector'
$dist = Join-Path $OutputRoot $name
$work = if ($WorkRoot) { $WorkRoot } else { Join-Path $root 'build' }

$pythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
    (Join-Path $env:ProgramFiles 'Python311\python.exe')
)
$pythonCommand = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$pythonArgs = @()
if (-not $pythonCommand) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.11 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $launcher.Source
            $pythonArgs = @('-3.11')
        }
    }
}
if (-not $pythonCommand) { throw 'Python 3.11 was not found.' }

Write-Host '[1/5] checking PyInstaller...'
& $pythonCommand @pythonArgs -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '      installing PyInstaller...'
    & $pythonCommand @pythonArgs -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
}

Write-Host '[2/5] checking PostgreSQL driver...'
& $pythonCommand @pythonArgs -c "import psycopg2" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '      installing psycopg2-binary...'
    & $pythonCommand @pythonArgs -m pip install psycopg2-binary
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL driver installation failed.' }
}

if (Test-Path -LiteralPath $dist) {
    $existingExe = Join-Path $dist "$name.exe"
    if (Test-Path -LiteralPath $existingExe) {
        try {
            $lockCheck = [System.IO.File]::Open(
                $existingExe,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::None
            )
            $lockCheck.Dispose()
        }
        catch {
            throw "Close $existingExe before rebuilding; the running program is using it."
        }
    }
}

Write-Host '[3/5] building (this may take several minutes)...'
& $pythonCommand @pythonArgs -m PyInstaller --noconfirm --clean `
    --distpath $OutputRoot `
    --workpath $work `
    $spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

if (-not (Test-Path -LiteralPath $dist)) { throw "build output missing: $dist" }

Write-Host '[4/5] copying strategy presets next to exe...'
Copy-Item -LiteralPath (Join-Path $root 'stock_selector\presets.yaml')    -Destination $dist -Force
Copy-Item -LiteralPath (Join-Path $root 'stock_selector\presets_v2.yaml') -Destination $dist -Force

Write-Host '[5/5] done.'
Write-Host "exe: $dist\$name.exe"
Write-Host 'Distribute the whole folder. presets*.yaml sit next to the exe and are editable.'
