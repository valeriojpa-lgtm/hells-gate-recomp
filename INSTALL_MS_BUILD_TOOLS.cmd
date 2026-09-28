@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Microsoft C++ Build Tools prerequisite
echo ============================================================
echo.
echo This is the ONLY non-portable prerequisite for the Windows build.
echo It provides the Windows SDK and Microsoft link libraries used by Clang.
echo.
echo The portable builder will NOT run this automatically.
echo Continue only if BUILD_DANTE_PORTABLE.cmd tells you it is missing.
echo.
pause

set "BOOTSTRAP=%TEMP%\vs_BuildTools.exe"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing 'https://aka.ms/vs/17/release/vs_BuildTools.exe' -OutFile '%BOOTSTRAP%'"
if errorlevel 1 goto :fail

"%BOOTSTRAP%" --passive --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended
if errorlevel 1 goto :fail

echo.
echo Build Tools installation finished.
echo Restart Windows if the Microsoft installer asks you to, then run
echo BUILD_DANTE_PORTABLE.cmd again.
echo.
pause
exit /b 0

:fail
echo.
echo Build Tools setup failed. Exit code: %ERRORLEVEL%
echo.
pause
exit /b %ERRORLEVEL%
