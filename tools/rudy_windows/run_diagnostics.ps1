param(
    [Parameter(Mandatory=$false)]
    [string]$RudyDir = "third_party\clash-royale-suite\cr-rudy-sim\simulator",

    [Parameter(Mandatory=$false)]
    [string]$HarnessDir = "tools\cr_hog_fidelity_test",

    [Parameter(Mandatory=$false)]
    [string]$VenvPath = ".venv-rudy"
)

$ErrorActionPreference = "Stop"

$python = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Rudy venv not found at $VenvPath"
}

if (-not (Test-Path $RudyDir)) {
    throw "Rudy source/data not found at $RudyDir. Run run_fidelity.ps1 first."
}

$RudyDir = (Resolve-Path $RudyDir).Path
$HarnessDir = (Resolve-Path $HarnessDir).Path
$out = Join-Path $HarnessDir "sim_out\hog_diagnostic.json"

& $python (Join-Path $HarnessDir "diagnose_rudy.py") `
    --config (Join-Path $HarnessDir "scenarios.json") `
    --real (Join-Path $HarnessDir "fixtures\real\hog_solo.json") `
    --data-dir (Join-Path $RudyDir "data") `
    --out $out

Write-Host ""
Write-Host "Diagnostic saved to: $out"
