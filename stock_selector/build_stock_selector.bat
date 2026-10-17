@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "BUILD_SCRIPT=%SCRIPT_DIR%build_gui.ps1"
set "OUTPUT_ROOT=%SCRIPT_DIR%..\dist"

if not exist "%BUILD_SCRIPT%" (
    echo Build script not found: %BUILD_SCRIPT%
    pause
    exit /b 1
)

echo Building StockSelector directly into E:\trading\dist\StockSelector...

tasklist /FI "IMAGENAME eq StockSelector.exe" /NH 2>nul | find /I "StockSelector.exe" >nul
if "%ERRORLEVEL%"=="0" (
    echo A running StockSelector.exe was detected.
    choice /C YN /N /M "Close the current program and continue packaging? [Y/N]"
    if errorlevel 2 (
        echo Packaging cancelled. The current program was left running.
        pause
        exit /b 2
    )
    taskkill /IM StockSelector.exe /T /F >nul 2>&1
    timeout /t 1 /nobreak >nul
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BUILD_SCRIPT%" -OutputRoot "%OUTPUT_ROOT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Build failed. Exit code: %EXIT_CODE%
    pause
    exit /b %EXIT_CODE%
)

echo.
echo Build complete: E:\trading\dist\StockSelector\StockSelector.exe
pause
exit /b 0
