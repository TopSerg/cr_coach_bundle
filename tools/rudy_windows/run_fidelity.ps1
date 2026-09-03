param(
    [Parameter(Mandatory=$false)]
    [string]$RudyDir = "third_party\clash-royale-suite\cr-rudy-sim\simulator",

    [Parameter(Mandatory=$false)]
    [string]$HarnessDir = "tools\cr_hog_fidelity_test",

    [Parameter(Mandatory=$false)]
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found at $VenvPath. Run tools\rudy_windows\install_rudy.ps1 first."
}
$python = (Resolve-Path $venvPython).Path

if (-not (Test-Path $RudyDir)) {
    Write-Host "Rudy source/data checkout not found. Downloading source WITHOUT compiling Rust..."
    New-Item -ItemType Directory -Force -Path "third_party" | Out-Null

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is required to fetch Rudy data/source. Install Git for Windows or place clash-royale-suite under third_party manually."
    }

    if (Test-Path "third_party\clash-royale-suite") {
        Remove-Item -Recurse -Force "third_party\clash-royale-suite"
    }

    git clone --depth 1 https://github.com/nguiaSoren/clash-royale-suite.git third_party\clash-royale-suite
}

$RudyDir = (Resolve-Path $RudyDir).Path
$HarnessDir = (Resolve-Path $HarnessDir).Path
$dataDir = Join-Path $RudyDir "data"
$outDir = Join-Path $HarnessDir "sim_out"
$config = Join-Path $HarnessDir "scenarios.json"

Write-Host ""
Write-Host "Python:"
& $python --version

Write-Host ""
Write-Host "Checking cr_engine import..."
& $python -c "import cr_engine; print('cr_engine import OK')"

Write-Host ""
Write-Host "Running Rudy fidelity scenarios..."
& $python (Join-Path $HarnessDir "run_rudy.py") `
    --scenario all `
    --config $config `
    --data-dir $dataDir `
    --out-dir $outDir

Write-Host ""
Write-Host "Comparing HOG SOLO..."
$soloReport = Join-Path $outDir "hog_solo_report.json"
& $python (Join-Path $HarnessDir "compare.py") `
    (Join-Path $HarnessDir "fixtures\real\hog_solo.json") `
    (Join-Path $outDir "hog_solo_trace.json") `
    --out $soloReport
$soloExit = $LASTEXITCODE

Write-Host ""
Write-Host "Comparing HOG VS PREPLACED CANNON..."
$cannonReport = Join-Path $outDir "hog_cannon_report.json"
& $python (Join-Path $HarnessDir "compare.py") `
    (Join-Path $HarnessDir "fixtures\real\hog_vs_cannon_preplaced.json") `
    (Join-Path $outDir "hog_cannon_trace.json") `
    --out $cannonReport
$cannonExit = $LASTEXITCODE

Write-Host ""
Write-Host "========================================="
Write-Host "FIDELITY RUN COMPLETE"
Write-Host "========================================="
Write-Host "Solo report:   $soloReport"
Write-Host "Cannon report: $cannonReport"

if ($soloExit -ne 0 -or $cannonExit -ne 0) {
    Write-Host ""
    Write-Host "One or more probes DIVERGED from the real demos."
    Write-Host "That is a useful simulator result, not necessarily a harness error."
    exit 2
}

Write-Host ""
Write-Host "Both probes are inside configured tolerances."
exit 0
