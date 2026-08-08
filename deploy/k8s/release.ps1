param(
  [Parameter(Mandatory = $true)]
  [string]$ExpectedContext,
  [string]$Namespace = 'workbuddy-hub'
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = Join-Path $ScriptRoot 'base'
$Migration = Join-Path $ScriptRoot 'migration-job.yaml'

$currentContext = kubectl config current-context
if ($LASTEXITCODE -ne 0 -or $currentContext -ne $ExpectedContext) {
  throw "Kubernetes context mismatch. Expected '$ExpectedContext', got '$currentContext'."
}

python (Join-Path $ScriptRoot 'preflight.py') --base $Base --migration $Migration
if ($LASTEXITCODE -ne 0) {
  throw 'Kubernetes production preflight failed.'
}

$foundation = @(
  'namespace.yaml',
  'service-account.yaml',
  'configmap.yaml',
  'service.yaml',
  'pod-disruption-budget.yaml',
  'ingress.yaml',
  'network-policy.yaml'
)
foreach ($file in $foundation) {
  kubectl apply -f (Join-Path $Base $file)
  if ($LASTEXITCODE -ne 0) { throw "Failed to apply $file." }
}

kubectl --namespace $Namespace get secret hub-api-secrets | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw 'Required externally managed Secret hub-api-secrets does not exist.'
}

$existingMigration = kubectl --namespace $Namespace get job hub-api-migrate --ignore-not-found -o name
if ($LASTEXITCODE -ne 0) {
  throw 'Failed to inspect the previous migration Job.'
}
if ($existingMigration) {
  throw 'Migration Job hub-api-migrate already exists. Archive its logs and delete it explicitly before this release.'
}
kubectl apply -f $Migration
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the migration Job.' }
kubectl --namespace $Namespace wait --for=condition=complete job/hub-api-migrate --timeout=10m
if ($LASTEXITCODE -ne 0) {
  kubectl --namespace $Namespace logs job/hub-api-migrate --tail=100
  throw 'Database migration failed; the Deployment was not updated.'
}

kubectl apply -k $Base
if ($LASTEXITCODE -ne 0) { throw 'Failed to apply the Hub API workload.' }
kubectl --namespace $Namespace rollout status deployment/hub-api --timeout=5m
if ($LASTEXITCODE -ne 0) { throw 'Hub API rollout did not complete.' }

kubectl --namespace $Namespace get deployment/hub-api service/hub-api ingress/hub-api
