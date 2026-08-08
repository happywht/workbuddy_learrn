param(
  [string]$BaseUrl = 'http://127.0.0.1:8100'
)

$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'smoke.py') $BaseUrl
if ($LASTEXITCODE -ne 0) { throw "Hub smoke failed" }
