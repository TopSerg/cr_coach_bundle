# Invoke the two-emulator lab with py.exe from any working directory.
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Repo
try {
    & py -m emulator_lab @Arguments
    if ($LASTEXITCODE -ne 0) { throw "emulator_lab exited $LASTEXITCODE" }
}
finally {
    Pop-Location
}
