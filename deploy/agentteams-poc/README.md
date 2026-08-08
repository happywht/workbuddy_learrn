# AgentTeams PoC preflight

The repository does not contain an official single-node AgentTeams Compose
stack. The upstream project provides an installer and an official Helm chart,
so deployment must happen in an isolated host or Kubernetes namespace.

`agentteams-preflight.ps1` checks the inputs that can be verified before an
install is attempted:

- upstream checkout and pinned commit;
- official Helm chart and required values;
- `helm`, `kubectl`, and `docker` availability;
- isolated Kubernetes namespace;
- HTTPS requirements for non-local Controller and Matrix endpoints;
- presence of real LLM and Matrix admin secrets without printing them.

Example (PowerShell; secrets are passed through the process environment):

```powershell
$env:AGENTTEAMS_LLM_API_KEY = '<secret from the PoC secret manager>'
$env:AGENTTEAMS_ADMIN_PASSWORD = '<separate Matrix admin password>'
.\agentteams-preflight.ps1 `
  -UpstreamPath "$env:TEMP\workbuddy-upstream-audit\agentteams" `
  -ControllerUrl 'https://teams-poc.example/internal/controller' `
  -MatrixUrl 'https://teams-poc.example' `
  -OutputPath '.\reports\agentteams-preflight.json'
```

Exit codes:

- `0`: all preflight checks passed; an operator may proceed to the official
  Helm/installer flow.
- `2`: one or more checks failed. No deployment should be attempted.

This is a readiness report, not an AgentTeams deployment or end-to-end smoke
test. After installation, the operator still must verify Team Admin auth,
Matrix room membership, Worker readiness, file access isolation, cancellation,
and a two-agent de-identified task through the Hub Adapter.
