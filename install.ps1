# DeepanCode Windows PowerShell One-Click Installer
# Run in PowerShell: .\install.ps1

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Installing DeepanCode AI Agent (Windows) " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# Check Python availability
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python 3 is required but not found in PATH." -ForegroundColor Red
    exit 1
}

Write-Host "[1/3] Upgrading pip and installing required dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -e .

Write-Host "[2/3] Verifying installation..." -ForegroundColor Yellow
python -c "import deepans_code; print('Deepans-code module successfully imported!')"

Write-Host "[3/3] Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To start DeepanCode, run:" -ForegroundColor Cyan
Write-Host "    deepans-code" -ForegroundColor White
Write-Host "Or:" -ForegroundColor Cyan
Write-Host "    python -m deepans_code" -ForegroundColor White
Write-Host ""
Write-Host "To configure one-time API keys:" -ForegroundColor Yellow
Write-Host "    deepans-code" -ForegroundColor White
Write-Host "    /connect openrouter <YOUR_API_KEY>" -ForegroundColor White
