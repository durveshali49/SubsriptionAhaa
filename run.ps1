Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv-app\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Create .venv-app and install requirements.txt first. See RUNNING.md.'
}
& $projectPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
