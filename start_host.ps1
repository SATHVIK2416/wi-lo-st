# SonicSync PowerShell Launcher
$Host.UI.RawUI.WindowTitle = "SonicSync Lossless Multi-Room Audio Host"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   🎵  SonicSync — Lossless Multi-Room Wireless Audio System" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

$pythonExists = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExists) {
    Write-Host "[ERROR] Python was not found on your system." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ and make sure it is added to your PATH." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[*] Launching SonicSync Host..." -ForegroundColor Green
python run.py --mode host --source test
