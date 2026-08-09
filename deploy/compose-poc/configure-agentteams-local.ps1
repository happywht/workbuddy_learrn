[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot ".env"),
    [string]$HumanName = "workbuddy-hub"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.Encoding]::ASCII

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "WorkBuddy local env file does not exist: $EnvFile"
}

$controller = & docker ps --format "{{.Names}}" | Where-Object { $_ -eq "agentteams-controller" }
if (-not $controller) {
    throw "agentteams-controller is not running."
}

$humanRaw = & docker exec agentteams-controller agt get humans $HumanName -o json
if ($LASTEXITCODE -ne 0 -or -not $humanRaw) {
    throw "AgentTeams Human '$HumanName' is not available."
}
$human = $humanRaw | ConvertFrom-Json
if (-not $human.matrixUserID -or -not $human.initialPassword) {
    throw "AgentTeams Human '$HumanName' has no local Matrix login credentials."
}

$password = $human.initialPassword
$loginJson = @{
    type = "m.login.password"
    identifier = @{ type = "m.id.user"; user = $HumanName }
    password = $password
} | ConvertTo-Json -Compress -Depth 5
$tempLogin = Join-Path ([IO.Path]::GetTempPath()) "workbuddy-matrix-login-$([guid]::NewGuid().ToString('N')).json"
try {
    [IO.File]::WriteAllText($tempLogin, $loginJson, (New-Object Text.UTF8Encoding($false)))
    & docker cp $tempLogin "agentteams-controller:/tmp/workbuddy-matrix-login.json" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to stage the local Matrix login request."
    }
    $loginRaw = & docker exec agentteams-controller curl -sf `
        -X POST http://127.0.0.1:6167/_matrix/client/v3/login `
        -H "Content-Type: application/json" -d "@/tmp/workbuddy-matrix-login.json"
} finally {
    Remove-Item -LiteralPath $tempLogin -Force -ErrorAction SilentlyContinue
    & docker exec agentteams-controller rm -f /tmp/workbuddy-matrix-login.json *> $null
}
if ($LASTEXITCODE -ne 0 -or -not $loginRaw) {
    throw "Matrix login failed for AgentTeams Human '$HumanName'."
}
$login = $loginRaw | ConvertFrom-Json
if (-not $login.access_token -or $login.user_id -ne $human.matrixUserID) {
    throw "Matrix login returned an unexpected identity."
}

$controllerToken = (& docker exec agentteams-controller cat /var/run/agentteams/cli-token).Trim()
if ($LASTEXITCODE -ne 0 -or -not $controllerToken) {
    throw "AgentTeams Controller token is unavailable."
}

$serverName = ($human.matrixUserID -split ":", 2)[1]
$settings = [ordered]@{
    AGENTTEAMS_BASE_URL = "http://agentteams-controller:8090"
    AGENTTEAMS_TOKEN = $controllerToken
    AGENTTEAMS_MATRIX_URL = "http://agentteams-controller:6167"
    AGENTTEAMS_MATRIX_TOKEN = $login.access_token
    AGENTTEAMS_MATRIX_USER_ID = $login.user_id
    AGENTTEAMS_MATRIX_MEDIA_SERVER_ALLOWLIST = $serverName
    AGENTTEAMS_MATRIX_MEDIA_MAX_BYTES = "26214400"
}

$lines = [System.Collections.Generic.List[string]]::new()
Get-Content -LiteralPath $EnvFile | ForEach-Object { [void]$lines.Add($_) }
foreach ($entry in $settings.GetEnumerator()) {
    $prefix = "$($entry.Key)="
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].StartsWith($prefix, [StringComparison]::Ordinal)) {
            $index = $i
            break
        }
    }
    $line = "$prefix$($entry.Value)"
    if ($index -ge 0) {
        $lines[$index] = $line
    } else {
        [void]$lines.Add($line)
    }
}
[IO.File]::WriteAllLines($EnvFile, $lines, [Text.Encoding]::ASCII)

Write-Host "AgentTeams connector configured for $($login.user_id)."
Write-Host "Controller: http://agentteams-controller:8090"
Write-Host "Matrix:     http://agentteams-controller:6167"
