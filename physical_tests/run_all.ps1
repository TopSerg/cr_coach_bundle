$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not (Test-Path "upstream/cr-bot/simulator")) {
    Write-Host "Initializing upstream/cr-bot submodule..."
    git submodule update --init upstream/cr-bot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

python physical_tests/run_all.py
exit $LASTEXITCODE
