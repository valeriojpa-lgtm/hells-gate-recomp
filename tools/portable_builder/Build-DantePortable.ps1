param(
    [switch]$KeepBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Portable    = Join-Path $ProjectRoot ".portable"
$Downloads   = Join-Path $Portable "downloads"
$Logs        = Join-Path $ProjectRoot "logs"
$GameDir     = Join-Path $ProjectRoot "game"
$SdkDir      = Join-Path $ProjectRoot "thirdparty\rexglue-sdk"
$BuildDir    = Join-Path $ProjectRoot "out\build\win-amd64-release"
$PackageDir  = Join-Path $ProjectRoot "out\portable\Dantes_Inferno_RUN00"

New-Item -ItemType Directory -Force -Path $Portable,$Downloads,$Logs | Out-Null
$Transcript = Join-Path $Logs "portable_builder.log"
try { Start-Transcript -Path $Transcript -Force | Out-Null } catch { }

function Step([string]$Text) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkCyan
}

function Fail([string]$Text) {
    Write-Host ""
    Write-Host "ERROR: $Text" -ForegroundColor Red
    throw $Text
}

function Verify-Hash([string]$Path, [string]$Sha256) {
    if (-not $Sha256) { return }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256.ToLowerInvariant()) {
        Remove-Item -Force -LiteralPath $Path -ErrorAction SilentlyContinue
        Fail "SHA-256 mismatch for $Path"
    }
}

function Download-File([string]$Url, [string]$Destination, [string]$Sha256 = "") {
    if (Test-Path -LiteralPath $Destination) {
        try {
            Verify-Hash $Destination $Sha256
            Write-Host "Cached: $(Split-Path -Leaf $Destination)" -ForegroundColor DarkGray
            return
        } catch {
            Remove-Item -Force -LiteralPath $Destination -ErrorAction SilentlyContinue
        }
    }
    Write-Host "Downloading: $Url" -ForegroundColor Yellow
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
    Verify-Hash $Destination $Sha256
}

function Expand-ZipFresh([string]$Zip, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) { Remove-Item -Recurse -Force -LiteralPath $Destination }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Expand-Archive -LiteralPath $Zip -DestinationPath $Destination -Force
}

function Add-ToolPath([string]$Path) {
    if ($Path -and (Test-Path -LiteralPath $Path)) {
        $env:Path = "$Path;$env:Path"
    }
}

function Import-VsEnvironment {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere)) { return $false }

    $install = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
    if (-not $install) { return $false }

    $vsDevCmd = Join-Path $install "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $vsDevCmd)) { return $false }

    $tempBat = Join-Path $env:TEMP "dante_vs_environment.cmd"
    @(
        "@echo off",
        "call `"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 >nul",
        "set"
    ) | Set-Content -Encoding ASCII -LiteralPath $tempBat

    $dump = & $env:ComSpec /d /c $tempBat
    Remove-Item -Force -LiteralPath $tempBat -ErrorAction SilentlyContinue
    foreach ($line in $dump) {
        if ($line -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
        }
    }
    Write-Host "Visual Studio C++ environment: $install" -ForegroundColor Green
    return $true
}

function Validate-Game {
    Step "[0/7] Validate preserved Dante's Inferno build"
    foreach ($p in @("CMakeLists.txt","setup.ps1","dantes_inferno_manifest.toml","patches\generated\apply_generated_patches.py")) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $p))) {
            Fail "This builder must be extracted into the ROOT of hells-gate-recomp. Missing: $p"
        }
    }

    $files = @(
        @{ Name="default.xex";  Size=10760192;   Hash="abfef19fa03a247ab17d5c011e34ca70a0338f13c15b7fd8932c7ff7d9e2c2e9" },
        @{ Name="default.xexp"; Size=2205696;    Hash="0842733820a27e0c902e6a652b3cd71d2c4a05f36db5121c1d342416a6b7ab09" },
        @{ Name="bigfile0.viv"; Size=3176365408; Hash="" },
        @{ Name="bigfile1.viv"; Size=2692050613; Hash="" }
    )

    foreach ($f in $files) {
        $path = Join-Path $GameDir $f.Name
        if (-not (Test-Path -LiteralPath $path)) {
            if ($f.Name -eq "bigfile0.viv") { Fail "game\bigfile0.viv is missing. Rename bigfile0-001.viv to bigfile0.viv if needed." }
            if ($f.Name -eq "bigfile1.viv") { Fail "game\bigfile1.viv is missing. Rename bigfile1-002.viv to bigfile1.viv if needed." }
            Fail "Missing required file: game\$($f.Name)"
        }
        $size = (Get-Item -LiteralPath $path).Length
        if ($size -ne [int64]$f.Size) { Fail "Unexpected size for game\$($f.Name): $size bytes" }
        if ($f.Hash) {
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
            if ($hash -ne $f.Hash) {
                if ($f.Name -eq "default.xexp") {
                    Fail "default.xexp is NOT the matching TU2 extracted from your GOD. Restore your Velocity-extracted default.xexp."
                }
                Fail "SHA-256 mismatch for game\$($f.Name)"
            }
        }
        Write-Host "PASS  game\$($f.Name)" -ForegroundColor Green
    }
}

function Bootstrap-Tools {
    Step "[1/7] Prepare portable build tools"

    $gitRoot = Join-Path $Portable "mingit"
    $gitExe = Join-Path $gitRoot "cmd\git.exe"
    if (-not (Test-Path $gitExe)) {
        $zip = Join-Path $Downloads "MinGit-2.55.0.5-64-bit.zip"
        Download-File "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.5/MinGit-2.55.0.5-64-bit.zip" $zip "56d7b226b7693196cfc71fef26568f536c4a021ab6c37ff2db4287bed908e96e"
        Expand-ZipFresh $zip $gitRoot
    }

    $cmakeRoot = Join-Path $Portable "cmake"
    $cmakeExe = Get-ChildItem -Path $cmakeRoot -Recurse -Filter cmake.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmakeExe) {
        $zip = Join-Path $Downloads "cmake-4.4.3-windows-x86_64.zip"
        Download-File "https://github.com/Kitware/CMake/releases/download/v4.4.3/cmake-4.4.3-windows-x86_64.zip" $zip "4d52ebab7193a698651639ed80d8d04fd903358843572cf44c7fd234cb7c26ab"
        Expand-ZipFresh $zip $cmakeRoot
        $cmakeExe = Get-ChildItem -Path $cmakeRoot -Recurse -Filter cmake.exe | Select-Object -First 1
    }

    $ninjaRoot = Join-Path $Portable "ninja"
    $ninjaExe = Join-Path $ninjaRoot "ninja.exe"
    if (-not (Test-Path $ninjaExe)) {
        $zip = Join-Path $Downloads "ninja-win-1.13.2.zip"
        Download-File "https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip" $zip "07fc8261b42b20e71d1720b39068c2e14ffcee6396b76fb7a795fb460b78dc65"
        Expand-ZipFresh $zip $ninjaRoot
    }

    $pythonRoot = Join-Path $Portable "python"
    $pythonExe = Join-Path $pythonRoot "python.exe"
    if (-not (Test-Path $pythonExe)) {
        $zip = Join-Path $Downloads "python-3.12.10-embed-amd64.zip"
        Download-File "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip" $zip
        Expand-ZipFresh $zip $pythonRoot
    }

    $llvmRoot = Join-Path $Portable "llvm"
    $clangExe = Join-Path $llvmRoot "bin\clang.exe"
    if (-not (Test-Path $clangExe)) {
        $archive = Join-Path $Downloads "clang+llvm-20.1.8-x86_64-pc-windows-msvc.tar.xz"
        Download-File "https://github.com/llvm/llvm-project/releases/download/llvmorg-20.1.8/clang%2Bllvm-20.1.8-x86_64-pc-windows-msvc.tar.xz" $archive "f229769f11d6a6edc8ada599c0cda964b7dee6ab1a08c6cf9dd7f513e85b107f"

        $stage = Join-Path $Portable "llvm-stage"
        if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
        New-Item -ItemType Directory -Force -Path $stage | Out-Null

        $tar = (Get-Command tar.exe -ErrorAction SilentlyContinue).Source
        if (-not $tar) { $tar = Join-Path $gitRoot "usr\bin\tar.exe" }
        if (-not (Test-Path $tar)) { Fail "No tar.exe available to unpack portable LLVM." }
        & $tar -xf $archive -C $stage
        if ($LASTEXITCODE -ne 0) { Fail "Could not unpack portable LLVM." }

        $inner = Get-ChildItem -Directory -Path $stage | Select-Object -First 1
        if (-not $inner) { Fail "Portable LLVM archive did not contain the expected directory." }
        if (Test-Path $llvmRoot) { Remove-Item -Recurse -Force $llvmRoot }
        Move-Item -LiteralPath $inner.FullName -Destination $llvmRoot
        Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    }

    Add-ToolPath (Join-Path $gitRoot "cmd")
    Add-ToolPath (Split-Path $cmakeExe.FullName -Parent)
    Add-ToolPath $ninjaRoot
    Add-ToolPath $pythonRoot
    Add-ToolPath (Join-Path $llvmRoot "bin")

    $env:GIT_TERMINAL_PROMPT = "0"

    Write-Host "Git:    $(& git --version)" -ForegroundColor DarkGray
    Write-Host "CMake:  $((& cmake --version | Select-Object -First 1))" -ForegroundColor DarkGray
    Write-Host "Ninja:  $(& ninja --version)" -ForegroundColor DarkGray
    Write-Host "Python: $(& python --version)" -ForegroundColor DarkGray
    Write-Host "Clang:  $((& clang --version | Select-Object -First 1))" -ForegroundColor DarkGray
}

function Repair-LibmspackWindowsLinks {
    $libRoot = Join-Path $SdkDir "thirdparty\libmspack"
    $linkRoot = Join-Path $libRoot "cabextract\mspack"
    if (-not (Test-Path -LiteralPath $linkRoot)) { return }

    $fixed = 0
    Get-ChildItem -LiteralPath $linkRoot -File | ForEach-Object {
        $item = $_
        if ($item.Length -gt 256) { return }

        $targetText = (Get-Content -LiteralPath $item.FullName -Raw).Trim()
        if ($targetText -notmatch '^\.\./\.\./\.\./libmspack/mspack/') { return }

        $targetRelative = $targetText -replace '/', '\'
        $targetFull = [System.IO.Path]::GetFullPath((Join-Path $item.DirectoryName $targetRelative))
        if (-not (Test-Path -LiteralPath $targetFull)) {
            Fail "libmspack Windows symlink target is missing: $targetFull"
        }

        Copy-Item -Force -LiteralPath $targetFull -Destination $item.FullName
        $fixed++
    }

    if ($fixed -gt 0) {
        Write-Host "Materialized $fixed libmspack symlinks for Windows." -ForegroundColor Green
    } else {
        Write-Host "libmspack Windows symlinks already materialized." -ForegroundColor DarkGray
    }
}

function Prepare-Sdk {
    Step "[2/7] Prepare ReXGlue SDK v0.10.0 + Hell's Gate patches"
    $thirdparty = Join-Path $ProjectRoot "thirdparty"
    New-Item -ItemType Directory -Force -Path $thirdparty | Out-Null

    if ((Test-Path $SdkDir) -and -not (Test-Path (Join-Path $SdkDir ".git"))) {
        Fail "thirdparty\rexglue-sdk exists but is not a Git checkout. Rename/delete that folder and run again."
    }

    if (-not (Test-Path (Join-Path $SdkDir ".git"))) {
        & git clone --branch v0.10.0 --depth 1 https://github.com/rexglue/rexglue-sdk.git $SdkDir
        if ($LASTEXITCODE -ne 0) { Fail "ReXGlue SDK clone failed." }
    }

    & git -C $SdkDir submodule update --init --recursive --depth 1
    if ($LASTEXITCODE -ne 0) { Fail "ReXGlue SDK submodule download failed." }

    # libmspack ships cabextract/mspack as POSIX symlinks. Standard Windows
    # Git checkouts materialize them as tiny text files, which Clang then
    # mistakes for C source. Copy each link target over the placeholder.
    Repair-LibmspackWindowsLinks

    & (Join-Path $ProjectRoot "patches\apply_sdk_patches.ps1") -SdkDir "thirdparty\rexglue-sdk"
    if ($LASTEXITCODE -ne 0) { Fail "Hell's Gate ReXGlue SDK patch failed." }
}

function Clean-Generated {
    if ($KeepBuild) { return }
    Step "[3/7] Clean stale generated code/build output"
    $generated = Join-Path $ProjectRoot "generated\default"
    if (Test-Path $generated) { Remove-Item -Recurse -Force $generated }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
    Write-Host "Clean baseline ready." -ForegroundColor Green
}

function Run-CMake([string[]]$Arguments) {
    & cmake @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "CMake failed: cmake $($Arguments -join ' ')" }
}

function Build-Project {
    Step "[4/7] Configure + generate C++ from YOUR default.xex"
    Push-Location $ProjectRoot
    try {
        Run-CMake @("--preset","win-amd64-release","-DREXSDK_DIR=thirdparty\rexglue-sdk","-DDANTESINFERNO_NATIVE_RENDERER=OFF")
        Run-CMake @("--build","out\build\win-amd64-release","--target","dantes_inferno_codegen","--parallel")

        Step "[5/7] Apply Hell's Gate generated-code fixes"
        & python "patches\generated\apply_generated_patches.py"
        if ($LASTEXITCODE -ne 0) { Fail "Generated-code patch script failed." }

        Run-CMake @("--preset","win-amd64-release","-DREXSDK_DIR=thirdparty\rexglue-sdk","-DDANTESINFERNO_NATIVE_RENDERER=OFF")

        Step "[6/7] Compile RUN 00 (D3D12 baseline)"
        Run-CMake @("--build","out\build\win-amd64-release","--target","dantes_inferno","--parallel")
        Run-CMake @("--build","out\build\win-amd64-release","--target","rexgpu-xenos","--parallel")
    }
    finally {
        Pop-Location
    }
}

function Find-BuiltFile([string]$Name) {
    $candidates = @(
        (Join-Path $BuildDir $Name),
        (Join-Path $SdkDir "out\win-amd64\$Name")
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $found = Get-ChildItem -Path $BuildDir,$SdkDir -Recurse -File -Filter $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

function Package-Run00 {
    Step "[7/7] Package fresh RUN 00 executable"
    if (Test-Path $PackageDir) { Remove-Item -Recurse -Force $PackageDir }
    New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir "logs") | Out-Null

    $exe = Find-BuiltFile "dantes_inferno.exe"
    $runtime = Find-BuiltFile "rexruntime.dll"
    $gpu = Find-BuiltFile "rexgpu-xenos.dll"
    if (-not $exe) { Fail "dantes_inferno.exe was not produced." }
    if (-not $runtime) { Fail "rexruntime.dll was not produced." }
    if (-not $gpu) { Fail "rexgpu-xenos.dll was not produced." }

    Copy-Item -Force $exe (Join-Path $PackageDir "Dante's Inferno.exe")
    Copy-Item -Force $runtime $PackageDir
    Copy-Item -Force $gpu $PackageDir

    foreach ($dll in @("amd_fidelityfx_dx12.dll","amd_fidelityfx_vk.dll")) {
        $p = Find-BuiltFile $dll
        if ($p) { Copy-Item -Force $p $PackageDir }
    }

    $shaderCache = Join-Path $ProjectRoot "shader_cache"
    if (Test-Path $shaderCache) { Copy-Item -Recurse -Force $shaderCache $PackageDir }

    $launch = @'
@echo off
setlocal
cd /d "%~dp0"

set "GAME=%~dp0game"
if not exist "%GAME%\default.xex" set "GAME=%~dp0..\..\..\game"
if not exist "%GAME%\default.xex" (
  echo Could not find game\default.xex.
  echo Either keep RUN00 inside the project or copy your game folder beside this launcher.
  pause
  exit /b 1
)

if not exist logs mkdir logs
"%~dp0Dante's Inferno.exe" --game_data_root="%GAME%" --gpu_backend=d3d12 --log_level=info --log_file="%~dp0logs\RUN00.log"
exit /b %ERRORLEVEL%
'@
    Set-Content -Encoding ASCII -LiteralPath (Join-Path $PackageDir "LAUNCH_RUN00.cmd") -Value $launch

    $xexHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $GameDir "default.xex")).Hash.ToLowerInvariant()
    $xexpHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $GameDir "default.xexp")).Hash.ToLowerInvariant()
    $exeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PackageDir "Dante's Inferno.exe")).Hash.ToLowerInvariant()
    $info = @"
Dante's Inferno - RUN 00 fresh local recompilation

Source project: valeriojpa-lgtm/hells-gate-recomp
Branch target: q01-vanilla-baseline
ReXGlue SDK: v0.10.0 + project patch
Renderer: D3D12 / Xenos (native renderer disabled for baseline)

Input default.xex SHA-256:  $xexHash
Input default.xexp SHA-256: $xexpHash
Output EXE SHA-256:         $exeHash

The executable was regenerated from the user's own local Xbox 360 XEX.
No game files are uploaded by BUILD_DANTE_PORTABLE.cmd.
"@
    Set-Content -Encoding UTF8 -LiteralPath (Join-Path $PackageDir "BUILD_INFO.txt") -Value $info

    Write-Host ""
    Write-Host "RUN 00 BUILD PASS" -ForegroundColor Green
    Write-Host "Output: $PackageDir" -ForegroundColor Green
    Write-Host "Launch: $(Join-Path $PackageDir 'LAUNCH_RUN00.cmd')" -ForegroundColor Green
}

try {
    Set-Location $ProjectRoot
    Validate-Game

    Step "Windows SDK / MSVC library check"
    if (-not (Import-VsEnvironment)) {
        Write-Host "Visual Studio 2022 C++ Build Tools were not detected." -ForegroundColor Yellow
        Write-Host "Nothing has been installed or changed." -ForegroundColor Yellow
        Write-Host "Run INSTALL_MS_BUILD_TOOLS.cmd once, then rerun this builder." -ForegroundColor Yellow
        exit 20
    }

    Bootstrap-Tools
    Prepare-Sdk
    Clean-Generated
    Build-Project
    Package-Run00
    exit 0
}
catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "See: $Transcript" -ForegroundColor Yellow
    exit 1
}
finally {
    try { Stop-Transcript | Out-Null } catch { }
}
