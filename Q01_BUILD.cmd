@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Dante's Inferno - Hell's Gate Recomp
echo   Q01 VANILLA BASELINE BUILD
echo ============================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\q01_build_windows.ps1"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo ============================================================
    echo   Q01 BUILD PASS
    echo ============================================================
) else (
    echo ============================================================
    echo   Q01 BUILD FAILED - exit code %RC%
    echo ============================================================
)

echo.
pause
exit /b %RC%
