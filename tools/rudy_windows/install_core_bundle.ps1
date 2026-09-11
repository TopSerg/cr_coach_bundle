param(
    [Parameter(Mandatory = $true)]
    [string]$Bundle,
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BundlePath = (Resolve-Path $Bundle).Path
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("cr-rudy-" + [guid]::NewGuid().ToString("N"))

try {
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    Expand-Archive -Path $BundlePath -DestinationPath $TempRoot
    $Wheel = Get-ChildItem -Path $TempRoot -Recurse -Filter "*.whl" | Select-Object -First 1
    $Data = Get-ChildItem -Path $TempRoot -Recurse -Directory -Filter "rudy_tournament11_data" | Select-Object -First 1
    if (-not $Wheel) { throw "The bundle does not contain a Python wheel." }
    if (-not $Data) { throw "The bundle does not contain rudy_tournament11_data." }

    & $Python -m pip install --force-reinstall $Wheel.FullName
    if ($LASTEXITCODE -ne 0) { throw "Wheel installation failed with exit code $LASTEXITCODE" }

    $Target = Join-Path $RepoRoot ".rudy\data"
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -Path (Join-Path $Data.FullName "*") -Destination $Target -Recurse -Force
    & $Python -c "import cr_engine; print(cr_engine)"
    if ($LASTEXITCODE -ne 0) { throw "cr_engine import check failed" }

    Write-Host "Rudy installed. Run:" -ForegroundColor Green
    Write-Host "  $Python simulate.py examples\hog_cannon_secondary.json --out outputs\secondary"
}
finally {
    if (Test-Path $TempRoot) { Remove-Item -Path $TempRoot -Recurse -Force }
}
