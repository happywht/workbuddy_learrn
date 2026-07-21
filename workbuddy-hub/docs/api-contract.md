# WorkBuddy Hub API / MCP Contract

## Trust Boundary

- Browser input is untrusted.
- Package content is untrusted until validation passes.
- Actor identity comes from the authenticated connector or web session, not from package JSON.
- A requested scope is not an authorization grant.
- User confirmation is required for publication but does not replace service-side authorization.

## Artifact Model

```text
Artifact
├─ immutable identity
├─ kind: case | skill
├─ current version
├─ visibility scope
├─ owner and department binding
├─ package metadata and files
├─ ratings and reuse events
├─ reports and moderation state
└─ append-only audit events
```

## MCP Tools

| Tool | Side effect | Purpose |
| --- | --- | --- |
| `registry.search` | No | Search accessible cases and Skills. |
| `registry.get` | No | Read one accessible artifact and version. |
| `registry.publish_preview` | Temporary draft | Validate package and calculate allowed scopes. |
| `registry.publish` | Yes | Publish a confirmed preview. |
| `registry.update` | Yes | Publish a new immutable version. |
| `registry.rate` | Yes | Record a post-use rating. |
| `registry.report` | Yes | Report unsafe, broken, or misleading content. |
| `registry.rollback` | Yes | Restore an earlier version while keeping history. |

## REST Equivalents

```text
GET    /api/v1/artifacts
GET    /api/v1/artifacts/{artifact_id}
POST   /api/v1/publication-previews
POST   /api/v1/publications
POST   /api/v1/artifacts/{artifact_id}/versions
POST   /api/v1/artifacts/{artifact_id}/ratings
POST   /api/v1/artifacts/{artifact_id}/reports
POST   /api/v1/artifacts/{artifact_id}/rollback
```

## Scope Rules

### Personal

Owner-only by default. The service binds the artifact to the authenticated actor.

### Department

Requires a department target resolved from the actor context. The service checks membership or delegated publication authority.

### Institute

Requires organization-wide publication authority defined by the registry policy. Department membership alone is not sufficient.

## Publication State Machine

```text
draft
  -> preview_validated
  -> user_confirmed
  -> authorized
  -> published
```

Failure paths preserve the draft:

```text
preview_validated -> sanitization_required
user_confirmed -> scope_denied
authorized -> publish_failed
published -> reported -> hidden | restored
```

There is no pre-publication reviewer state. Automatic validation and service-side authorization are not editorial review.

## Required Audit Events

- preview created;
- automated validation result;
- scope selected;
- explicit confirmation recorded;
- authorization result;
- publication created;
- version updated;
- rating submitted;
- content reported, hidden, restored, or rolled back.

The audit log must not store raw access tokens or full sensitive input files.
