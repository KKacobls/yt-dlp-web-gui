$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  throw "Python launcher (py) was not found. Install Python 3.12: winget install -e --id Python.Python.3.12"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "Please install Node.js 20+ from https://nodejs.org/"
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  throw "Please install FFmpeg: winget install --id Gyan.FFmpeg -e"
}
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
  throw "ffprobe was not found. Check the FFmpeg installation."
}

$venvPath = Join-Path $PWD.Path ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$rebuild = -not (Test-Path $venvPython)

if (-not $rebuild) {
  try {
    $currentVersion = & $venvPython -c "import sys; print('%d.%d' % (sys.version_info.major, sys.version_info.minor))"
    if ($LASTEXITCODE -ne 0 -or "$currentVersion".Trim() -ne "3.12") {
      $rebuild = $true
    }
  } catch {
    $rebuild = $true
  }
}

if ($rebuild) {
  if (Test-Path $venvPath) {
    Write-Host "Existing environment is not Python 3.12. Rebuilding .venv..." -ForegroundColor Yellow
    Remove-Item -LiteralPath $venvPath -Recurse -Force
  }
  Write-Host "Creating Python 3.12 environment..." -ForegroundColor Cyan
  & py -3.12 -m venv $venvPath
  if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 is required. Install it with: winget install -e --id Python.Python.3.12"
  }
}

& $venvPython -m pip install -r "backend\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed" }

Push-Location frontend
try {
  if (Test-Path "package-lock.json") { npm ci }
  else { npm install }
  if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
} finally { Pop-Location }

Write-Host ""
Write-Host "Open: http://127.0.0.1:8765" -ForegroundColor Green
Start-Process "http://127.0.0.1:8765"
& $venvPython -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8765
