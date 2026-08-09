[CmdletBinding()]
param(
    [string]$ProjectName = "workbuddy-hub-local"
)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "compose.yaml"
$envFile = Join-Path $PSScriptRoot ".env"
$composeArgs = @(
    "compose", "--project-name", $ProjectName,
    "--file", $composeFile
)
if (Test-Path -LiteralPath $envFile) {
    $composeArgs += @("--env-file", $envFile)
}

& docker @composeArgs down --remove-orphans
