# `hub-api-secrets` contract

The Kubernetes Secret is created by the organization Secret Manager integration. It is not checked into this repository.

Required keys:

- `HUB_DATABASE_URL`: PostgreSQL SQLAlchemy URL for the Hub-owned database.
- `HUB_SKILLHUB_TOKEN`: least-privilege SkillHub service credential.
- `HUB_AGENTTEAMS_TOKEN`: least-privilege AgentTeams Controller credential.
- `HUB_AGENTTEAMS_MATRIX_TOKEN`: token for the dedicated Matrix Hub identity.

The Secret must exist in namespace `workbuddy-hub` before the migration Job runs. Rotation requires a controlled Deployment restart and an authentication smoke test. A shared global administrator credential is not allowed.
