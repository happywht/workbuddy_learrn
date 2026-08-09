[CmdletBinding()]
param(
    [int]$HubPort = 8100,
    [int]$PortalPort = 4173,
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
$agentTeamsNetwork = "agentteams-net"

if (-not (Test-Path -LiteralPath $envFile)) {
    $passwordBytes = New-Object byte[] 24
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $random.GetBytes($passwordBytes)
    $random.Dispose()
    $localPassword = -join ($passwordBytes | ForEach-Object { $_.ToString("x2") })
    @(
        "HUB_PORT=$HubPort"
        "PORTAL_PORT=$PortalPort"
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

& docker network inspect $agentTeamsNetwork *> $null
if ($LASTEXITCODE -ne 0) {
    & docker network create $agentTeamsNetwork *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the local AgentTeams integration network."
    }
}

$agentTeamsController = & docker ps --format "{{.Names}}" | Where-Object { $_ -eq "agentteams-controller" }
$agentTeamsConfigured = $envContent -match "(?m)^AGENTTEAMS_MATRIX_TOKEN=\S+"
if ($agentTeamsController -and -not $agentTeamsConfigured) {
    & (Join-Path $PSScriptRoot "configure-agentteams-local.ps1") -EnvFile $envFile
    if ($LASTEXITCODE -ne 0) {
        throw "AgentTeams is running, but automatic Hub connector configuration failed."
    }
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
    $portalQuery = if ($HubPort -eq 8100) { "" } else { "?apiBase=http://127.0.0.1:$HubPort" }
    Write-Host ""
    Write-Host "Hub API:     http://127.0.0.1:$HubPort"
    Write-Host "Portal:      http://127.0.0.1:$PortalPort"
    Write-Host "SkillHub UI: http://127.0.0.1:$PortalPort/skills/$portalQuery"
    Write-Host "AgentTeams:  http://127.0.0.1:$PortalPort/collaboration/$portalQuery"
    Write-Host "API docs:    http://127.0.0.1:$HubPort/docs"
    Write-Host "Health:      http://127.0.0.1:$HubPort/health"
    Write-Host "Smoke test:  python deploy/compose-poc/smoke.py http://127.0.0.1:$HubPort"
    Write-Host "Local actor: local-dev (injected only on localhost)"
}
finally {
    Pop-Location
}
