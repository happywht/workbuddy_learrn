[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UpstreamPath,
    [string]$ExpectedCommit = "552d0fb54d697b0689dafb6a01740e1a5f507552",
    [string]$ExpectedRelease = "v1.2.1",
    [string]$Namespace = "agentteams-poc",
    [string]$ControllerUrl = "",
    [string]$MatrixUrl = "",
    [string]$LlmApiKey = [Environment]::GetEnvironmentVariable("AGENTTEAMS_LLM_API_KEY"),
    [string]$AdminPassword = [Environment]::GetEnvironmentVariable("AGENTTEAMS_ADMIN_PASSWORD"),
    [string]$OutputPath = ""
)

$checks = @()

function Add-Check {
    param(
        [string]$Id,
        [ValidateSet("pass", "warn", "fail")]
        [string]$Status,
        [string]$Detail
    )
    $script:checks += [pscustomobject]@{
        id = $Id
        status = $Status
        detail = $Detail
    }
}

function Test-Tool {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-SecretValue {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    return $Value -notmatch "(?i)placeholder|changeme|change-me|example|dummy|test-only"
}

$resolvedPath = $null
try {
    $resolvedPath = (Resolve-Path -LiteralPath $UpstreamPath -ErrorAction Stop).Path
} catch {
    Add-Check "upstream_path" "fail" "Upstream checkout does not exist."
}

if ($resolvedPath) {
    $head = (& git -C $resolvedPath rev-parse HEAD 2>$null).Trim()
    if ($LASTEXITCODE -eq 0 -and $head) {
        if ($head -eq $ExpectedCommit) {
            Add-Check "source_commit" "pass" "Checkout is pinned to the audited commit."
        } else {
            Add-Check "source_commit" "fail" "Expected $ExpectedCommit but found $head."
        }
    } else {
        Add-Check "source_commit" "fail" "Path is not a readable Git checkout."
    }

    $tagCommit = (& git -C $resolvedPath rev-parse ("refs/tags/" + $ExpectedRelease) 2>$null).Trim()
    if ($LASTEXITCODE -eq 0 -and $tagCommit) {
        if ($tagCommit -eq $ExpectedCommit) {
            Add-Check "release_ref" "pass" "Expected release ref resolves to the pinned commit."
        } else {
            Add-Check "release_ref" "fail" "Expected release ref resolves to $tagCommit, not $ExpectedCommit."
        }
    } else {
        Add-Check "release_ref" "warn" "Expected release ref is not present in the local checkout; fetch it before deployment."
    }

    $chartPath = Join-Path $resolvedPath "helm\agentteams\Chart.yaml"
    if (Test-Path -LiteralPath $chartPath) {
        $chart = Get-Content -LiteralPath $chartPath -Raw
        $chartVersion = ([regex]::Match($chart, '(?m)^version:\s*["'']?([^\s"'']+)["'']?')).Groups[1].Value
        $chartAppVersion = ([regex]::Match($chart, '(?m)^appVersion:\s*["'']?([^\s"'']+)["'']?')).Groups[1].Value
        Add-Check "helm_chart" "pass" "Chart found (version=$chartVersion, appVersion=$chartAppVersion; expected release=$ExpectedRelease)."
    } else {
        Add-Check "helm_chart" "fail" "helm/agentteams/Chart.yaml is missing."
    }

    $valuesPath = Join-Path $resolvedPath "helm\agentteams\values.yaml"
    if (Test-Path -LiteralPath $valuesPath) {
        $values = Get-Content -LiteralPath $valuesPath -Raw
        foreach ($required in @("credentials:", "llmApiKey:", "adminPassword:", "preflight:", "matrix:", "storage:", "controller:")) {
            if ($values -match [regex]::Escape($required)) {
                Add-Check ("chart_value_" + $required.TrimEnd(':').Replace('-', '_')) "pass" "Required chart value is declared."
            } else {
                Add-Check ("chart_value_" + $required.TrimEnd(':').Replace('-', '_')) "fail" "Required chart value '$required' is absent."
            }
        }
    } else {
        Add-Check "helm_values" "fail" "helm/agentteams/values.yaml is missing."
    }
}

foreach ($tool in @("helm", "kubectl", "docker")) {
    if (Test-Tool $tool) {
        Add-Check ("tool_" + $tool) "pass" "$tool is available."
    } else {
        Add-Check ("tool_" + $tool) "fail" "$tool is required for the official deployment path."
    }
}

if ($Namespace -match "[^a-z0-9-]" -or $Namespace.Length -lt 1 -or $Namespace.Length -gt 63) {
    Add-Check "namespace" "fail" "Namespace must be a DNS label of 1-63 lowercase characters."
} else {
    Add-Check "namespace" "pass" "Namespace is isolated as '$Namespace'."
}

foreach ($endpoint in @(
    [pscustomobject]@{ Id = "controller_url"; Value = $ControllerUrl },
    [pscustomobject]@{ Id = "matrix_url"; Value = $MatrixUrl }
)) {
    if ([string]::IsNullOrWhiteSpace($endpoint.Value)) {
        Add-Check $endpoint.Id "fail" "Endpoint was not supplied."
        continue
    }
    try {
        $uri = [Uri]$endpoint.Value
        $isLocal = $uri.Host -in @("localhost", "127.0.0.1", "::1")
        if ($uri.Scheme -ne "https" -and -not $isLocal) {
            Add-Check $endpoint.Id "fail" "Non-local endpoint must use HTTPS."
        } else {
            Add-Check $endpoint.Id "pass" "Endpoint scheme and host are acceptable."
        }
    } catch {
        Add-Check $endpoint.Id "fail" "Endpoint is not a valid URL."
    }
}

if (Test-SecretValue $LlmApiKey) {
    Add-Check "llm_api_key" "pass" "LLM API key is supplied without logging its value."
} else {
    Add-Check "llm_api_key" "fail" "A real LLM API key is required; placeholders are rejected."
}

if (Test-SecretValue $AdminPassword) {
    Add-Check "admin_password" "pass" "Admin password is supplied without logging its value."
} else {
    Add-Check "admin_password" "fail" "A non-placeholder Matrix admin password is required for smoke tests."
}

$ready = @($checks | Where-Object { $_.status -eq "fail" }).Count -eq 0
$report = [pscustomobject]@{
    generated_at = [DateTime]::UtcNow.ToString("o")
    expected_release = $ExpectedRelease
    expected_commit = $ExpectedCommit
    upstream_path = $UpstreamPath
    namespace = $Namespace
    ready_for_install = $ready
    checks = $checks
}

$json = $report | ConvertTo-Json -Depth 6
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $parent = Split-Path -Parent $OutputPath
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Set-Content -LiteralPath $OutputPath -Value $json -Encoding utf8
}
$checks | Format-Table -Property id, status, detail -AutoSize
if (-not $ready) {
    exit 2
}
