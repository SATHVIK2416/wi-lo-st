# SonicSync PowerShell Launcher
$Host.UI.RawUI.WindowTitle = "SonicSync Lossless Multi-Room Audio Host"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   SonicSync — Lossless Multi-Room Wireless Audio System" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

$pythonExists = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExists) {
    Write-Host "[ERROR] Python was not found on your system." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ and make sure it is added to your PATH." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Prefer the project virtual environment; create it on first run
if (Test-Path ".venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
    Write-Host "[*] Using virtual environment .venv" -ForegroundColor Green
} else {
    Write-Host "[*] No .venv found - creating one (first run only)..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    & ".\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    $python = ".\.venv\Scripts\python.exe"
}

Write-Host "[*] Launching SonicSync Host..." -ForegroundColor Green
& $python run.py --mode host --source test

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] SonicSync exited with code $LASTEXITCODE." -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
