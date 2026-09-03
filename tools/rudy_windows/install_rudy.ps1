param(
    [Parameter(Mandatory=$false)]
    [string]$WheelPath,

    [Parameter(Mandatory=$false)]
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
    param([string]$Venv)

    $venvPython = Join-Path $Venv "Scripts\python.exe"
    if (Test-Path $venvPython) {
        return (Resolve-Path $venvPython).Path
    }

    Write-Host "Creating virtual environment at $Venv ..."
    py -3 -m venv $Venv
    if (-not (Test-Path $venvPython)) {
        throw "Could not create venv. Make sure Python is installed and 'py' launcher is available."
    }
    return (Resolve-Path $venvPython).Path
}

$python = Resolve-Python -Venv $VenvPath

Write-Host ""
Write-Host "Python used:"
& $python --version

if (-not $WheelPath) {
    $searchRoots = @(
        (Join-Path (Get-Location) "downloads"),
        (Join-Path $HOME "Downloads"),
        (Get-Location).Path
    )

    $candidates = @()
    foreach ($dir in $searchRoots) {
        if (Test-Path $dir) {
            $candidates += Get-ChildItem -Path $dir -Filter "cr_engine-*.whl" -File -Recurse -ErrorAction SilentlyContinue
        }
    }

    $candidates = $candidates | Sort-Object LastWriteTime -Descending

    if ($candidates.Count -eq 0) {
        throw @"
No cr_engine wheel found.

Download the GitHub Actions artifact that matches your Python version,
extract the ZIP, then rerun:

  powershell -ExecutionPolicy Bypass -File tools\rudy_windows\install_rudy.ps1 -WheelPath "C:\path\to\cr_engine-....whl"
"@
    }

    $WheelPath = $candidates[0].FullName
    Write-Host "Auto-selected wheel: $WheelPath"
}

$WheelPath = (Resolve-Path $WheelPath).Path

Write-Host ""
Write-Host "Installing Rudy binary wheel ..."
& $python -m pip install --upgrade pip
& $python -m pip install --force-reinstall $WheelPath

Write-Host ""
Write-Host "Verifying native module import ..."
& $python -c "import cr_engine; print('Rudy OK:', cr_engine)"

if ($LASTEXITCODE -ne 0) {
    throw "cr_engine import failed."
}

Write-Host ""
Write-Host "SUCCESS: Rudy is installed. Rust is not required for normal use."
Write-Host "Next:"
Write-Host "  powershell -ExecutionPolicy Bypass -File tools\rudy_windows\run_fidelity.ps1"
