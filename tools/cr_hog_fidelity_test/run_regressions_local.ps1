param(
    [string]$Python = "python",
    [string]$DataDir = "outputs/rudy_tournament11_data",
    [string]$OutRoot = "outputs/rudy_local"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Run-Step([string]$Name, [scriptblock]$Body) {
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path $DataDir)) {
    throw "Tournament-11 data directory not found: $DataDir`nBuild it first or pass -DataDir <path>."
}

Run-Step "Check cr_engine" {
    & $Python -c "import cr_engine; print('cr_engine import: OK')"
}

$Existing = Join-Path $OutRoot "rudy_existing"
$Pathing = Join-Path $OutRoot "rudy_pathing"
$Postfix = Join-Path $OutRoot "rudy_postfix"
New-Item -ItemType Directory -Force -Path $Existing, $Pathing, $Postfix | Out-Null

Run-Step "Solo Hog + historical probes" {
    & $Python tools/cr_hog_fidelity_test/run_rudy.py `
        --scenario all `
        --config tools/cr_hog_fidelity_test/scenarios.json `
        --data-dir $DataDir `
        --out-dir $Existing
}

Write-Host ""
Write-Host "=== Compare solo Hog guard ===" -ForegroundColor Cyan
& $Python tools/cr_hog_fidelity_test/compare.py `
    tools/cr_hog_fidelity_test/fixtures/real/hog_solo.json `
    (Join-Path $Existing "hog_solo_trace.json") `
    --out (Join-Path $Existing "hog_solo_report.json")
$SoloExit = $LASTEXITCODE
if ($SoloExit -ne 0 -and $SoloExit -ne 2) {
    throw "Solo comparator crashed with exit code $SoloExit"
}

Run-Step "Bridge/pathing diagnostic" {
    & $Python tools/cr_hog_fidelity_test/run_primary_pathing.py `
        --data-dir $DataDir `
        --reference physical_tests/references/d03_hog_cannon_02_primary.json `
        --out-dir $Pathing
}

Run-Step "Video regressions" {
    & $Python tools/cr_hog_fidelity_test/run_postfix_regressions.py `
        --data-dir $DataDir `
        --references `
            physical_tests/references/d03_hog_cannon_02_primary.json `
            physical_tests/references/d03_hog_cannon_01_secondary.json `
            physical_tests/references/d02_hog_cannon_01_crossdemo.json `
        --out-dir $Postfix
}

$Summary = Join-Path $OutRoot "summary.md"
Run-Step "Readable summary" {
    & $Python tools/cr_hog_fidelity_test/render_regression_summary.py `
        --postfix-summary (Join-Path $Postfix "summary.json") `
        --solo-report (Join-Path $Existing "hog_solo_report.json") `
        --bridge-report (Join-Path $Pathing "bridge_corner_rudy.json") `
        --out $Summary
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Readable report: $Summary"
Write-Host "Full JSON traces: $OutRoot"
