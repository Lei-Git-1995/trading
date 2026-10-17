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
$stageRoot = Join-Path $OutputRoot '.StockSelector_build_tmp'
$stageDist = Join-Path $stageRoot $name
$stateBackup = Join-Path $stageRoot '_state'

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

try {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $stateBackup -Force | Out-Null

    # Preserve user data before replacing the formal package.
    if (Test-Path -LiteralPath $dist) {
        foreach ($stateName in @('data', 'logs', 'config.local.json', 'gui_crash.log')) {
            $statePath = Join-Path $dist $stateName
            if (Test-Path -LiteralPath $statePath) {
                Copy-Item -LiteralPath $statePath -Destination $stateBackup -Recurse -Force
            }
        }
    }

    Write-Host '[3/5] building in temporary directory (this may take several minutes)...'
    & $pythonCommand @pythonArgs -m PyInstaller --noconfirm --clean `
        --distpath $stageRoot `
        --workpath $work `
        $spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

    if (-not (Test-Path -LiteralPath (Join-Path $stageDist "$name.exe"))) {
        throw "build output missing: $stageDist"
    }

    Write-Host '[4/5] publishing package and preserving data/logs...'
    if (-not (Test-Path -LiteralPath $dist)) {
        New-Item -ItemType Directory -Path $dist -Force | Out-Null
    }
    foreach ($packageName in @('_internal', "$name.exe", 'presets.yaml', 'presets_v2.yaml')) {
        $target = Join-Path $dist $packageName
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
    $oldNested = Join-Path $dist $name
    if (Test-Path -LiteralPath $oldNested) {
        Remove-Item -LiteralPath $oldNested -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $stageDist '_internal') -Destination $dist -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $stageDist "$name.exe") -Destination $dist -Force
    Copy-Item -LiteralPath (Join-Path $root 'stock_selector\presets.yaml') -Destination $dist -Force
    Copy-Item -LiteralPath (Join-Path $root 'stock_selector\presets_v2.yaml') -Destination $dist -Force
    if (Test-Path -LiteralPath $stateBackup) {
        Get-ChildItem -LiteralPath $stateBackup -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $dist -Recurse -Force
        }
    }

    Write-Host '[5/5] done.'
    Write-Host "exe: $dist\$name.exe"
    Write-Host 'Distribute the whole folder. presets*.yaml sit next to the exe and are editable.'
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
