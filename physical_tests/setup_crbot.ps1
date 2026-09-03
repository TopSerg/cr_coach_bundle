$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Dest = Join-Path $RepoRoot ".physical_deps/cr-bot"
$Pin = "40ca2b16bc276fc982a3aa80c7415b24439cbd3c"
$Remote = "https://github.com/Keschler/cr-bot.git"

if ((Test-Path (Join-Path $Dest "simulator")) -and (Test-Path (Join-Path $Dest ".git"))) {
    $Head = (git -C $Dest rev-parse HEAD 2>$null).Trim()
    if ($LASTEXITCODE -eq 0 -and $Head -eq $Pin) {
        Write-Host "cr-bot simulator already prepared at $Pin"
        exit 0
    }
}

Write-Host "Preparing lightweight cr-bot simulator checkout..."
Write-Host "Only simulator/ will be materialized; the full upstream repository is not downloaded."

New-Item -ItemType Directory -Force (Split-Path $Dest) | Out-Null
if (-not (Test-Path (Join-Path $Dest ".git"))) {
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    git init $Dest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    git -C $Dest remote add origin $Remote
    git -C $Dest config remote.origin.promisor true
    git -C $Dest config remote.origin.partialclonefilter blob:none
    git -C $Dest config extensions.partialClone origin
    git -C $Dest sparse-checkout init --cone
    git -C $Dest sparse-checkout set simulator
}

git -C $Dest fetch --depth 1 --filter=blob:none origin $Pin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git -C $Dest checkout --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Head = (git -C $Dest rev-parse HEAD).Trim()
if ($Head -ne $Pin) {
    Write-Error "Expected cr-bot $Pin but got $Head"
    exit 1
}
if (-not (Test-Path (Join-Path $Dest "simulator"))) {
    Write-Error "Sparse checkout did not materialize simulator/"
    exit 1
}

Write-Host "Ready: $Dest"
Write-Host "Pinned commit: $Head"
