param(
    [Parameter(Mandatory=$false)]
    [string]$RudyDir = "third_party\clash-royale-suite\cr-rudy-sim\simulator",

    [Parameter(Mandatory=$false)]
    [string]$HarnessDir = "tools\cr_hog_fidelity_test",

    [Parameter(Mandatory=$false)]
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

$python = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Run install_rudy.ps1 first."
}

$RudyDir = (Resolve-Path $RudyDir).Path
$HarnessDir = (Resolve-Path $HarnessDir).Path

& $python (Join-Path $HarnessDir "grid_search_solo.py") `
    --config (Join-Path $HarnessDir "scenarios.json") `
    --real (Join-Path $HarnessDir "fixtures\real\hog_solo.json") `
    --data-dir (Join-Path $RudyDir "data") `
    --out-dir (Join-Path $HarnessDir "sim_out\grid")
