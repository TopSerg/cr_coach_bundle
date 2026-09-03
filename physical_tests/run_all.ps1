$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not (Test-Path ".physical_deps/cr-bot/simulator") -and -not (Test-Path "upstream/cr-bot/simulator")) {
    & "$PSScriptRoot/setup_crbot.ps1"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

python physical_tests/run_all.py
exit $LASTEXITCODE
