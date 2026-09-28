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
$BuildDir    = Join-Path $ProjectRoot "out\q01"
$PackageDir  = Join-Path $ProjectRoot "out\portable\Dantes_Inferno_RUN00"
$DiscLanguageReport = Join-Path $BuildDir "disc-languages.json"
$BaseLanguageId = 1
$BaseCountryId = 103

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

function Detect-DiscLanguages {
    Step "[3.5/7] Detect languages actually present in preserved VIV archives"
    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

    $detector = Join-Path $ProjectRoot "tools\portable_builder\detect_disc_languages.py"
    if (-not (Test-Path -LiteralPath $detector)) {
        Fail "Missing disc language detector: $detector"
    }

    & python $detector $GameDir --json $DiscLanguageReport
    if ($LASTEXITCODE -ne 0) {
        Fail "Disc language detection failed."
    }

    $script:BaseLanguageId = 1
    $script:BaseCountryId = 103
    $countryByLanguage = @{
        1 = 103  # English / United States
        2 = 53   # Japanese / Japan
        3 = 24   # German / Germany
        4 = 34   # French / France
        5 = 31   # Spanish / Spain
        6 = 50   # Italian / Italy
        7 = 56   # Korean / Korea
        8 = 20   # Chinese (Traditional)
        9 = 84   # Portuguese / Portugal
        11 = 82  # Polish / Poland
        12 = 88  # Russian / Russia
    }
    try {
        $detected = Get-Content -Raw -LiteralPath $DiscLanguageReport | ConvertFrom-Json
        if ($detected.found -and $detected.manifest -and $detected.manifest.text_languages) {
            $ids = @($detected.manifest.text_languages | ForEach-Object { [int]$_.id })
            if ($ids -contains 1) {
                $script:BaseLanguageId = 1
            } elseif ($ids.Count -gt 0) {
                $script:BaseLanguageId = $ids[0]
            }
            if ($countryByLanguage.ContainsKey($script:BaseLanguageId)) {
                $script:BaseCountryId = [int]$countryByLanguage[$script:BaseLanguageId]
            }
            $labels = @($detected.manifest.text_languages | ForEach-Object {
                "$($_.name) (ID $($_.id))"
            })
            Write-Host ("Disc text languages: " + ($labels -join ", ")) -ForegroundColor Green
            Write-Host "Base RUN locale: language $script:BaseLanguageId / country $script:BaseCountryId" -ForegroundColor Green
        } else {
            Write-Host "No authoritative VIV language manifest found; base RUN keeps English ID 1 / country 103." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Could not parse disc-languages.json; base RUN keeps English ID 1 / country 103." -ForegroundColor Yellow
        $script:BaseLanguageId = 1
        $script:BaseCountryId = 103
    }
}

function Repair-LibmspackWindowsLinks {
    $linkRoot = Join-Path $SdkDir "thirdparty\libmspack\cabextract\mspack"
    if (-not (Test-Path -LiteralPath $linkRoot)) { return }

    $fixed = 0
    Get-ChildItem -LiteralPath $linkRoot -File | ForEach-Object {
        $item = $_

        # Real source/header files are much larger. libmspack's POSIX symlinks
        # become tiny text files on a standard Windows checkout, containing a
        # relative target such as ../../libmspack/mspack/lzxd.c.
        if ($item.Length -gt 256) { return }

        $targetText = (Get-Content -LiteralPath $item.FullName -Raw).Trim()
        if ($targetText -notmatch '^\.\./') { return }
        if ($targetText -notmatch 'libmspack/mspack/') { return }

        $targetRelative = $targetText.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $targetFull = [System.IO.Path]::GetFullPath((Join-Path $item.DirectoryName $targetRelative))

        if (-not (Test-Path -LiteralPath $targetFull)) {
            Fail "libmspack symlink target is missing: $targetFull"
        }

        Copy-Item -Force -LiteralPath $targetFull -Destination $item.FullName
        Write-Host "Fixed libmspack link: $($item.Name)" -ForegroundColor DarkGray
        $fixed++
    }

    if ($fixed -gt 0) {
        Write-Host "Materialized $fixed libmspack symlinks for Windows." -ForegroundColor Green
    } else {
        Write-Host "libmspack symlinks are already real files." -ForegroundColor DarkGray
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

    # Always restore the SDK to the exact v0.10.0 baseline before applying
    # Hell's Gate's current patch. This makes the builder reproducible across
    # patch revisions instead of layering a new patch over an older patched
    # working tree ("does not match index").
    Write-Host "Restoring pristine ReXGlue v0.10.0 baseline..." -ForegroundColor DarkGray
    & git -C $SdkDir reset --hard v0.10.0
    if ($LASTEXITCODE -ne 0) {
        & git -C $SdkDir reset --hard f5337cdc947ff6d4c4196737e2c807a48f2a1fc2
        if ($LASTEXITCODE -ne 0) { Fail "Could not reset ReXGlue SDK to v0.10.0." }
    }

    & git -C $SdkDir submodule sync --recursive
    if ($LASTEXITCODE -ne 0) { Fail "ReXGlue SDK submodule sync failed." }

    & git -C $SdkDir submodule update --init --recursive --force --depth 1
    if ($LASTEXITCODE -ne 0) { Fail "ReXGlue SDK submodule download/reset failed." }

    # Reset modified tracked files inside every submodule too. In particular,
    # this restores libmspack's symlink placeholders after a previous build
    # materialized them as ordinary Windows files.
    & git -C $SdkDir submodule foreach --recursive "git reset --hard"
    if ($LASTEXITCODE -ne 0) { Fail "ReXGlue SDK submodule reset failed." }

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
    if (Test-Path $BuildDir) {
        try {
            Remove-Item -Recurse -Force -LiteralPath $BuildDir -ErrorAction Stop
        } catch {
            # Never let a stale Windows path block a fresh Q01 build. Rename
            # the old tree atomically and leave it outside the active build.
            $stale = Join-Path (Split-Path $BuildDir -Parent) ("q01_stale_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
            Rename-Item -LiteralPath $BuildDir -NewName (Split-Path $stale -Leaf) -ErrorAction Stop
            Write-Host "Old build tree moved aside: $stale" -ForegroundColor Yellow
        }
    }
    Write-Host "Clean Q01 baseline ready." -ForegroundColor Green
}

function Run-CMake([string[]]$Arguments) {
    & cmake @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "CMake failed: cmake $($Arguments -join ' ')" }
}

function Build-Project {
    Step "[4/7] SKU-adaptive codegen from YOUR default.xex + TU2"
    Push-Location $ProjectRoot
    try {
        $variantHelper = "tools\portable_builder\prepare_variant_manifest.py"
        if (-not (Test-Path -LiteralPath $variantHelper)) {
            Fail "Missing SKU-adaptive manifest helper: $variantHelper"
        }

        # Start from a cumulative preservation manifest: keep the upstream
        # entrypoints already proven necessary for indirect calls, then add
        # direct targets discovered from this exact XEX/TU2. Earlier Q01 builds
        # threw these seeds away, which produced a compiling executable with
        # missing runtime functions and a permanently black guest framebuffer.
        & python $variantHelper --reset
        if ($LASTEXITCODE -ne 0) { Fail "Could not create SKU-adaptive manifest." }

        $generated = Join-Path $ProjectRoot "generated\default"
        $converged = $false
        $maxPasses = 10

        for ($pass = 1; $pass -le $maxPasses; $pass++) {
            Write-Host ""
            Write-Host "Q01 discovery pass $pass/$maxPasses" -ForegroundColor Cyan

            # A changed manifest must produce a completely fresh function graph.
            if (Test-Path -LiteralPath $generated) {
                Remove-Item -Recurse -Force -LiteralPath $generated
            }

            Run-CMake @("--preset","win-amd64-release","-B","out\q01",
                "-DREXSDK_DIR=thirdparty\rexglue-sdk",
                "-DDANTESINFERNO_NATIVE_RENDERER=OFF",
                "-DDANTESINFERNO_FIDELITYFX=OFF")
            # Capture codegen output so validation failures caused by newly
            # discovered guest branch targets can be promoted automatically.
            # This is intentionally limited to "target not in any function";
            # every other codegen failure remains fatal.
            $codegenArgs = @("--build","out\q01","--target","dantes_inferno_codegen","--parallel")
            $codegenOutput = @(& cmake @codegenArgs 2>&1)
            $codegenExit = $LASTEXITCODE
            $codegenOutput | ForEach-Object { Write-Host $_ }

            # Preserve every discovery pass as evidence. This makes scanner /
            # graph regressions diagnosable after the build instead of relying
            # on terminal scrollback.
            $codegenEvidenceDir = Join-Path $BuildDir "preservation-evidence"
            New-Item -ItemType Directory -Force -Path $codegenEvidenceDir | Out-Null
            $codegenLog = Join-Path $codegenEvidenceDir ("codegen-pass-{0:D2}.log" -f $pass)
            $codegenOutput | Set-Content -Encoding UTF8 -LiteralPath $codegenLog

            if ($codegenExit -ne 0) {
                $validationTargets = New-Object System.Collections.Generic.HashSet[string]
                foreach ($line in $codegenOutput) {
                    $s = [string]$line
                    if ($s -match "0x([0-9A-Fa-f]{8}).*target not in any function") {
                        [void]$validationTargets.Add($Matches[1])
                    }
                }

                if ($validationTargets.Count -gt 0) {
                    Write-Host "Codegen exposed $($validationTargets.Count) validation target(s); promoting them into this SKU manifest..." -ForegroundColor Yellow
                    $helperArgs = @($variantHelper, "--add-targets") + @($validationTargets)
                    $promoteOutput = @(& python @helperArgs 2>&1)
                    $promoteOutput | ForEach-Object { Write-Host $_ }
                    if ($LASTEXITCODE -ne 0) { Fail "Could not promote codegen validation targets." }
                    continue
                }

                Fail "CMake codegen failed for a reason unrelated to adaptive target discovery."
            }

            $closureOutput = @(& python $variantHelper --close 2>&1)
            $closureOutput | ForEach-Object { Write-Host $_ }
            if ($LASTEXITCODE -ne 0) { Fail "SKU-adaptive manifest closure failed." }

            $joined = [string]::Join([Environment]::NewLine, $closureOutput)
            $match = [regex]::Match($joined, "ADDED=(\d+)")
            if (-not $match.Success) {
                Fail "SKU-adaptive manifest helper did not report ADDED=N."
            }
            $added = [int]$match.Groups[1].Value
            if ($added -eq 0) {
                $converged = $true
                Write-Host "Q01 function discovery converged on pass $pass." -ForegroundColor Green
                break
            }

            Write-Host "Discovered $added additional direct guest targets; regenerating..." -ForegroundColor Yellow
        }

        if (-not $converged) {
            Fail "SKU-adaptive function discovery did not converge after $maxPasses passes."
        }

        Step "[5/7] Apply signature-based generated-code fixes"
        & python "patches\generated\apply_generated_patches.py"
        if ($LASTEXITCODE -ne 0) { Fail "Generated-code patch script failed." }

        # Reconfigure after codegen so the final source list is imported.
        Run-CMake @("--preset","win-amd64-release","-B","out\q01",
            "-DREXSDK_DIR=thirdparty\rexglue-sdk",
            "-DDANTESINFERNO_NATIVE_RENDERER=OFF",
            "-DDANTESINFERNO_FIDELITYFX=OFF")

        # The generated patcher modifies codegen output after the codegen
        # stamp was created. Refresh the stamp so the build system doesn't run
        # codegen again and silently overwrite the patched sources.
        $codegenStamp = Join-Path $generated "codegen.build.stamp"
        if (Test-Path -LiteralPath $codegenStamp) {
            (Get-Item -LiteralPath $codegenStamp).LastWriteTime = Get-Date
        }

        Step "[6/7] Compile preservation RUN 00"
        Run-CMake @("--build","out\q01","--target","dantes_inferno","--parallel")
        Run-CMake @("--build","out\q01","--target","rexgpu-xenos","--parallel")

        # Exhaustive preservation gate: validate every preserved upstream seed,
        # generated direct trap count, fiber injections, retail inputs and
        # reproducibility invariants. This supersedes the old two-address spot check.
        $auditJson = Join-Path $BuildDir "preservation-static.json"
        $auditMarkdown = Join-Path $BuildDir "preservation-static.md"
        & python "tools\portable_builder\preservation_audit.py" --mode build --json $auditJson --markdown $auditMarkdown
        if ($LASTEXITCODE -ne 0) {
            Fail "Preservation static audit failed. See $auditMarkdown"
        }
        Write-Host "PASS exhaustive preservation static gates (runtime still unverified)." -ForegroundColor Green
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

    # Ship the runtime gate parser and the build-time static evidence with the
    # package. The parser contains no game data and can run after every launch.
    Copy-Item -Force (Join-Path $ProjectRoot "tools\portable_builder\analyze_run_log.py") $PackageDir
    Copy-Item -Force (Join-Path $ProjectRoot "tools\portable_builder\compare_run_reports.py") $PackageDir
    Copy-Item -Force (Join-Path $ProjectRoot "tools\portable_builder\run005_baseline.json") $PackageDir
    if (Test-Path -LiteralPath $DiscLanguageReport) {
        Copy-Item -Force $DiscLanguageReport (Join-Path $PackageDir "disc-languages.json")
    }
    foreach ($report in @("preservation-static.json","preservation-static.md")) {
        $src = Join-Path $BuildDir $report
        if (Test-Path -LiteralPath $src) { Copy-Item -Force $src $PackageDir }
    }
    $evidence = Join-Path $BuildDir "preservation-evidence"
    if (Test-Path -LiteralPath $evidence) {
        Copy-Item -Recurse -Force $evidence (Join-Path $PackageDir "preservation-evidence")
    }

    foreach ($dll in @("amd_fidelityfx_dx12.dll","amd_fidelityfx_vk.dll")) {
        $p = Find-BuiltFile $dll
        if ($p) { Copy-Item -Force $p $PackageDir }
    }

    # Q01 intentionally does not seed the upstream pre-generated shader cache.
    # A cache produced by another retail SKU can hide variant/codegen mistakes.

    $launch = @'
@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "GAME=%~dp0game"
if not exist "%GAME%\default.xex" set "GAME=%~dp0..\..\..\game"
if not exist "%GAME%\default.xex" (
  echo Could not find game\default.xex.
  echo Either keep RUN00 inside the project or copy your game folder beside this launcher.
  pause
  exit /b 1
)

rem Prefer fully portable state beside the executable, but never require
rem write access to the installation directory. Program Files and other
rem protected locations transparently fall back to LocalAppData.
set "STATE_ROOT=%~dp0userdata_base"
if not exist "!STATE_ROOT!" mkdir "!STATE_ROOT!" >nul 2>&1
> "!STATE_ROOT!\.preservation_write_test" echo writable 2>nul
if errorlevel 1 (
  set "STATE_ROOT=%LOCALAPPDATA%\HellsGatePreservation\RUN00-base"
  if not exist "!STATE_ROOT!" mkdir "!STATE_ROOT!" >nul 2>&1
  echo Portable directory is read-only; using "!STATE_ROOT!" for user data and logs.
) else (
  del /q "!STATE_ROOT!\.preservation_write_test" >nul 2>&1
)
if not exist "!STATE_ROOT!" (
  echo Could not create a writable user-data directory.
  exit /b 2
)

set "USERDATA=!STATE_ROOT!"
set "LOGDIR=!STATE_ROOT!\logs"
if not exist "!LOGDIR!" mkdir "!LOGDIR!" >nul 2>&1
> "!LOGDIR!\.preservation_write_test" echo writable 2>nul
if errorlevel 1 (
  echo Log directory is not writable: "!LOGDIR!"
  exit /b 3
)
del /q "!LOGDIR!\.preservation_write_test" >nul 2>&1

"%~dp0Dante's Inferno.exe" --game_data_root="%GAME%" --user_data_root="!USERDATA!" --gpu_backend=d3d12 --d3d12_adapter=1 --renderer=xenos --render_target_path_d3d12=rov --vsync=true --d3d12_host_vsync=true --video_mode_refresh_rate=60 --input_backend=sdl --enable_dlc=false --user_language=__BASE_LANGUAGE_ID__ --user_country=__BASE_COUNTRY_ID__ --log_level=debug --log_file="!LOGDIR!\RUN00.log"
set "GAME_EXIT=%ERRORLEVEL%"

rem Analyze every RUN automatically. Prefer the builder's portable Python when
rem this package is still inside the repository; fall back to the Python launcher.
set "PROJECT_PY=%~dp0..\..\..\.portable\python\python.exe"
set "ANALYZER=%~dp0analyze_run_log.py"
set "COMPARATOR=%~dp0compare_run_reports.py"
set "RUN005_BASELINE=%~dp0run005_baseline.json"
if exist "%PROJECT_PY%" (
  "%PROJECT_PY%" "%ANALYZER%" "!LOGDIR!\RUN00.log" --json "!LOGDIR!\RUN00.report.json" --markdown "!LOGDIR!\RUN00.report.md"
  if exist "!LOGDIR!\RUN00.report.json" if exist "%COMPARATOR%" if exist "%RUN005_BASELINE%" (
    "%PROJECT_PY%" "%COMPARATOR%" "!LOGDIR!\RUN00.report.json" --baseline "%RUN005_BASELINE%" --json "!LOGDIR!\RUN00.delta.json" --markdown "!LOGDIR!\RUN00.delta.md"
  )
  if exist "%~dp0..\..\..\tools\portable_builder\prepare_variant_manifest.py" (
    "%PROJECT_PY%" "%~dp0..\..\..\tools\portable_builder\prepare_variant_manifest.py" --learn-runtime-log "!LOGDIR!\RUN00.log"
  )
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    py "%ANALYZER%" "!LOGDIR!\RUN00.log" --json "!LOGDIR!\RUN00.report.json" --markdown "!LOGDIR!\RUN00.report.md"
    if exist "!LOGDIR!\RUN00.report.json" if exist "%COMPARATOR%" if exist "%RUN005_BASELINE%" (
      py "%COMPARATOR%" "!LOGDIR!\RUN00.report.json" --baseline "%RUN005_BASELINE%" --json "!LOGDIR!\RUN00.delta.json" --markdown "!LOGDIR!\RUN00.delta.md"
    )
  )
)

echo.
if exist "!LOGDIR!\RUN00.report.md" (
  echo RUN gate report: "!LOGDIR!\RUN00.report.md"
  if exist "!LOGDIR!\RUN00.delta.md" echo Historical delta: "!LOGDIR!\RUN00.delta.md"
) else (
  echo Runtime analyzer could not run automatically; the raw RUN00.log is preserved.
)
exit /b %GAME_EXIT%
'@
    $launch = $launch.Replace("__BASE_LANGUAGE_ID__", [string]$BaseLanguageId)
    $launch = $launch.Replace("__BASE_COUNTRY_ID__", [string]$BaseCountryId)
    Set-Content -Encoding ASCII -LiteralPath (Join-Path $PackageDir "LAUNCH_RUN00.cmd") -Value $launch

    $xexHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $GameDir "default.xex")).Hash.ToLowerInvariant()
    $xexpHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $GameDir "default.xexp")).Hash.ToLowerInvariant()
    $exePath = Join-Path $PackageDir "Dante's Inferno.exe"
    $runtimePath = Join-Path $PackageDir "rexruntime.dll"
    $gpuPath = Join-Path $PackageDir "rexgpu-xenos.dll"
    $exeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exePath).Hash.ToLowerInvariant()
    $runtimeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimePath).Hash.ToLowerInvariant()
    $gpuHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $gpuPath).Hash.ToLowerInvariant()

    $sourceCommit = ((& git -C $ProjectRoot rev-parse HEAD) | Select-Object -First 1).Trim()
    $sdkCommit = ((& git -C $SdkDir rev-parse HEAD) | Select-Object -First 1).Trim()
    $sdkPatchPath = Join-Path $ProjectRoot "patches\sdk\rexglue-sdk-v0.10.0.patch"
    $canonicalManifestPath = Join-Path $ProjectRoot "tools\portable_builder\upstream_manifest_base.toml"
    $seedPath = Join-Path $ProjectRoot "tools\portable_builder\upstream_function_seeds.txt"
    $runtimeSeedPath = Join-Path $ProjectRoot "tools\portable_builder\runtime_function_seeds.txt"
    $generatedManifestPath = Join-Path $ProjectRoot "dantes_inferno_manifest.toml"
    $registerPath = Join-Path $ProjectRoot "generated\default\dantes_inferno_register.cpp"
    $staticAuditPath = Join-Path $BuildDir "preservation-static.json"
    $run005BaselinePath = Join-Path $ProjectRoot "tools\portable_builder\run005_baseline.json"

    $sdkPatchHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sdkPatchPath).Hash.ToLowerInvariant()
    $canonicalManifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $canonicalManifestPath).Hash.ToLowerInvariant()
    $canonicalManifestGitBlob = ((& git hash-object $canonicalManifestPath) | Select-Object -First 1).Trim()
    $seedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $seedPath).Hash.ToLowerInvariant()
    $runtimeSeedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeSeedPath).Hash.ToLowerInvariant()
    $generatedManifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $generatedManifestPath).Hash.ToLowerInvariant()
    $registerHash = if (Test-Path -LiteralPath $registerPath) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $registerPath).Hash.ToLowerInvariant()
    } else { $null }
    $staticAuditHash = if (Test-Path -LiteralPath $staticAuditPath) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $staticAuditPath).Hash.ToLowerInvariant()
    } else { $null }
    $run005BaselineHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $run005BaselinePath).Hash.ToLowerInvariant()
    $discLanguageHash = if (Test-Path -LiteralPath $DiscLanguageReport) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $DiscLanguageReport).Hash.ToLowerInvariant()
    } else { $null }

    $provenance = [ordered]@{
        schema = 1
        generated_utc = (Get-Date).ToUniversalTime().ToString("o")
        source = [ordered]@{
            repository = "valeriojpa-lgtm/hells-gate-recomp"
            branch = "preservation-autofix"
            commit = $sourceCommit
        }
        retail = [ordered]@{
            title_id = "454108CF"
            media_id = "49028C6A"
            default_xex_sha256 = $xexHash
            default_xexp_sha256 = $xexpHash
            base_language_id = $BaseLanguageId
            base_country_id = $BaseCountryId
            disc_languages_sha256 = $discLanguageHash
        }
        sdk = [ordered]@{
            tag = "v0.10.0"
            commit = $sdkCommit
            patch_sha256 = $sdkPatchHash
        }
        preservation = [ordered]@{
            canonical_manifest_git_blob = $canonicalManifestGitBlob
            canonical_manifest_sha256 = $canonicalManifestHash
            generated_manifest_sha256 = $generatedManifestHash
            upstream_seed_ledger_sha256 = $seedHash
            runtime_seed_ledger_sha256 = $runtimeSeedHash
            generated_register_sha256 = $registerHash
            static_audit_sha256 = $staticAuditHash
            historical_run005_baseline_sha256 = $run005BaselineHash
        }
        artifacts = [ordered]@{
            exe_sha256 = $exeHash
            rexruntime_sha256 = $runtimeHash
            rexgpu_xenos_sha256 = $gpuHash
        }
        gates = [ordered]@{
            build_static = "PASS"
            runtime = "UNVERIFIED"
        }
    }
    $provenance | ConvertTo-Json -Depth 8 |
        Set-Content -Encoding UTF8 -LiteralPath (Join-Path $PackageDir "BUILD_PROVENANCE.json")

    $info = @"
Dante's Inferno - RUN 00 fresh local recompilation

Source project: valeriojpa-lgtm/hells-gate-recomp
Branch target: preservation-autofix
ReXGlue SDK: v0.10.0 + project patch
Codegen: SKU-adaptive discovery from this exact XEX + sibling TU2
Renderer: D3D12 / Xenos (native renderer disabled for baseline)
User/cache root: isolated base-campaign userdata_base; LocalAppData RUN00-base fallback otherwise
RUN00 launcher: RTX adapter 1 + official-compatible Xenos/D3D12 ROV + 60 Hz VSync + debug log
Base locale: language ID $BaseLanguageId / country ID $BaseCountryId
Language selected from authoritative VIV manifest when available; country follows upstream locale mapping.
Disc language report: disc-languages.json

Input default.xex SHA-256:  $xexHash
Input default.xexp SHA-256: $xexpHash
Output EXE SHA-256:         $exeHash
Source commit:               $sourceCommit
ReXGlue commit:              $sdkCommit
SDK patch SHA-256:           $sdkPatchHash
Canonical manifest blob:     $canonicalManifestGitBlob
Generated manifest SHA-256:  $generatedManifestHash

Structured provenance: BUILD_PROVENANCE.json

The executable was regenerated from the user's own local Xbox 360 XEX.
No game files are uploaded by BUILD_DANTE_PORTABLE.cmd.
"@
    Set-Content -Encoding UTF8 -LiteralPath (Join-Path $PackageDir "BUILD_INFO.txt") -Value $info

    Write-Host ""
    Write-Host "RUN 00 BUILD/STATIC GATES PASS - RUNTIME UNVERIFIED" -ForegroundColor Green
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
    Detect-DiscLanguages
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
