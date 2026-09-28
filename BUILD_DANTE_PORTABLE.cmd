@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Dante's Inferno - RUN 00 Portable Builder
echo ============================================================
echo.
echo This builder keeps Git, CMake, Ninja, Python and LLVM local
echo to this project folder. It does not add them to the system PATH.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\portable_builder\Build-DantePortable.ps1"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo ============================================================
    echo   RUN 00 BUILD PASS
    echo ============================================================
    echo Output: out\portable\Dantes_Inferno_RUN00
) else (
    echo ============================================================
    echo   BUILD STOPPED - exit code %RC%
    echo ============================================================
    echo Check logs\portable_builder.log for details.
)

echo.
pause
exit /b %RC%
