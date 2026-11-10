$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Please install Python 3.11+ from https://python.org/"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "Please install Node.js 20+ from https://nodejs.org/"
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  throw "Please install FFmpeg: winget install --id Gyan.FFmpeg -e"
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
  else { python -m venv .venv }
}
& ".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
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
& ".venv\Scripts\python.exe" -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8765
