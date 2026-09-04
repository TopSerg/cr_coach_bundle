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
    throw "Rudy Python environment not found at $VenvPath"
}

if (-not (Test-Path $RudyDir)) {
    throw "Rudy checkout not found at $RudyDir. Run the normal fidelity setup first."
}

$RudyDir = (Resolve-Path $RudyDir).Path
$HarnessDir = (Resolve-Path $HarnessDir).Path
$sourceData = Join-Path $RudyDir "data"
$profile = Join-Path $HarnessDir "tournament11_profile.json"
$generatedData = Join-Path $HarnessDir ".generated\tournament11_data"
$outDir = Join-Path $HarnessDir "sim_out\tournament11"
$config = Join-Path $HarnessDir "scenarios.json"
$real = Join-Path $HarnessDir "fixtures\real\hog_solo.json"

Write-Host ""
Write-Host "========================================="
Write-Host "BUILD TOURNAMENT-11 DATA OVERLAY"
Write-Host "========================================="
& $python (Join-Path $HarnessDir "build_tournament_data.py") `
    --source-data-dir $sourceData `
    --profile $profile `
    --out-dir $generatedData

Write-Host ""
Write-Host "========================================="
Write-Host "RUN HOG SOLO WITH TOURNAMENT-11 DATA"
Write-Host "========================================="
& $python (Join-Path $HarnessDir "run_rudy.py") `
    --scenario solo `
    --config $config `
    --data-dir $generatedData `
    --out-dir $outDir

Write-Host ""
Write-Host "========================================="
Write-Host "COMPARE AGAINST REAL VIDEO"
Write-Host "========================================="
$report = Join-Path $outDir "hog_solo_tournament11_report.json"
& $python (Join-Path $HarnessDir "compare.py") `
    $real `
    (Join-Path $outDir "hog_solo_trace.json") `
    --out $report
$compareExit = $LASTEXITCODE

Write-Host ""
Write-Host "========================================="
Write-Host "TOURNAMENT-11 RUN COMPLETE"
Write-Host "========================================="
Write-Host "Generated data: $generatedData"
Write-Host "Trace:          $(Join-Path $outDir 'hog_solo_trace.json')"
Write-Host "Report:         $report"
Write-Host ""
Write-Host "NOTE: this run overrides card DATA only."
Write-Host "Tower mechanics/pathfinding/projectile timing remain stock Rudy so any remaining"
Write-Host "difference is exactly what we want to investigate next."

if ($compareExit -ne 0) {
    Write-Host ""
    Write-Host "The simulator still diverges from the real demo after Tournament-11 overrides."
    exit 2
}

Write-Host "The simulator is inside the current fidelity tolerances."
exit 0
