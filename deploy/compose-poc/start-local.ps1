[CmdletBinding()]
param(
    [int]$HubPort = 8100,
    [int]$PostgresPort = 55432,
    [string]$ProjectName = "workbuddy-hub-local"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required. Start Docker Desktop and run this script again."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$composeFile = Join-Path $PSScriptRoot "compose.yaml"
$envFile = Join-Path $PSScriptRoot ".env"

if (-not (Test-Path -LiteralPath $envFile)) {
    $passwordBytes = New-Object byte[] 24
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $random.GetBytes($passwordBytes)
    $random.Dispose()
    $localPassword = -join ($passwordBytes | ForEach-Object { $_.ToString("x2") })
    @(
        "HUB_PORT=$HubPort"
        "POSTGRES_PORT=$PostgresPort"
        "POSTGRES_PASSWORD=$localPassword"
        "AUTH_MODE=local_header"
        "HUB_SEED_DEMO_CASES=true"
    ) | Set-Content -LiteralPath $envFile -Encoding ascii
    Write-Host "Created local Docker environment file: $envFile"
}

$envContent = Get-Content -Raw -LiteralPath $envFile
if ($envContent -notmatch "(?m)^POSTGRES_PASSWORD=\S+") {
    throw "POSTGRES_PASSWORD is missing in $envFile"
}

$composeArgs = @(
    "compose", "--project-name", $ProjectName,
    "--file", $composeFile,
    "--env-file", $envFile
)

Push-Location $repoRoot
try {
    & docker @composeArgs up --detach --build --wait
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed to start. Run 'docker compose logs hub-api' for details."
    }
    & docker @composeArgs ps
    Write-Host ""
    Write-Host "Hub API:     http://127.0.0.1:$HubPort"
    Write-Host "API docs:    http://127.0.0.1:$HubPort/docs"
    Write-Host "Health:      http://127.0.0.1:$HubPort/health"
    Write-Host "Smoke test:  python deploy/compose-poc/smoke.py http://127.0.0.1:$HubPort"
    Write-Host "Portal API:  add '?api=1' to the local WorkBuddy case page"
}
finally {
    Pop-Location
}
