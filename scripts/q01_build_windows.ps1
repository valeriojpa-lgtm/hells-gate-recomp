$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "== Dante's Inferno Q01 Vanilla Baseline ==" -ForegroundColor Cyan

$required = @(
    @{ Path = "game\default.xex";  Size = 10760192;   Sha256 = "ABFEF19FA03A247AB17D5C011E34CA70A0338F13C15B7FD8932C7FF7D9E2C2E9" },
    @{ Path = "game\default.xexp"; Size = 2205696;    Sha256 = "0842733820A27E0C902E6A652B3CD71D2C4A05F36DB5121C1D342416A6B7AB09" },
    @{ Path = "game\bigfile0.viv"; Size = 3176365408; Sha256 = $null },
    @{ Path = "game\bigfile1.viv"; Size = 2692050613; Sha256 = $null }
)

foreach ($item in $required) {
    $full = Join-Path $Root $item.Path
    if (-not (Test-Path $full)) {
        throw "Missing required file: $($item.Path)"
    }
    $actualSize = (Get-Item $full).Length
    if ($actualSize -ne $item.Size) {
        throw "Unexpected size for $($item.Path): $actualSize (expected $($item.Size))"
    }
    if ($item.Sha256) {
        $hash = (Get-FileHash -Algorithm SHA256 $full).Hash
        if ($hash -ne $item.Sha256) {
            throw "SHA-256 mismatch for $($item.Path): $hash"
        }
    }
    Write-Host "PASS  $($item.Path)" -ForegroundColor Green
}

foreach ($tool in @("git", "cmake", "ninja", "clang", "python")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Missing build prerequisite on PATH: $tool"
    }
}

Write-Host ""
Write-Host "[1/4] ReXGlue SDK setup" -ForegroundColor Yellow
& (Join-Path $Root "setup.ps1")

Write-Host ""
Write-Host "[2/4] Configure clean D3D12 baseline" -ForegroundColor Yellow
cmake --preset win-amd64-release -DREXSDK_DIR=thirdparty\rexglue-sdk -DDANTESINFERNO_NATIVE_RENDERER=OFF
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }

Write-Host ""
Write-Host "[3/4] Generate guest C++" -ForegroundColor Yellow
cmake --build out\build\win-amd64-release --target dantes_inferno_codegen
if ($LASTEXITCODE -ne 0) { throw "Codegen failed" }

Write-Host ""
Write-Host "[3.5/4] Apply project-specific generated-code patches" -ForegroundColor Yellow
python patches\generated\apply_generated_patches.py
if ($LASTEXITCODE -ne 0) { throw "Generated-code patch step failed" }

Write-Host ""
Write-Host "[4/4] Build vanilla baseline" -ForegroundColor Yellow
cmake --build out\build\win-amd64-release --target dantes_inferno
if ($LASTEXITCODE -ne 0) { throw "Final build failed" }

$exe = Join-Path $Root "out\build\win-amd64-release\dantes_inferno.exe"
if (-not (Test-Path $exe)) {
    throw "Build reported success but executable was not found: $exe"
}

Write-Host ""
Write-Host "Q01 BUILD PASS" -ForegroundColor Green
Write-Host "Executable: $exe"
Write-Host ""
Write-Host "Run it from the repository root so game\ remains available."
