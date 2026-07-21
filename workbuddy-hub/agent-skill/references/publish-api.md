# Registry Tool Contract

Use the WorkBuddy Hub registry connector. Authentication and actor identity are provided by the connector session and must not be embedded in tool arguments or package files.

## Required Tools

### `registry.search`

Search accessible artifacts before creating a duplicate.

```json
{
  "query": "project weekly report risk summary",
  "kind": "case",
  "tags": ["project"],
  "limit": 10
}
```

### `registry.publish_preview`

Validate and store a temporary non-public preview. This call must not publish.

```json
{
  "kind": "case",
  "requested_scope": "department",
  "target_department_id": "optional",
  "package": {},
  "source": {
    "task_summary": "sanitized summary",
    "agent": "WorkBuddy"
  }
}
```

Expected response:

```json
{
  "preview_id": "preview_...",
  "validation": { "status": "passed", "warnings": [] },
  "allowed_scopes": ["personal", "department"],
  "expires_at": "ISO-8601"
}
```

### `registry.publish`

Publish a validated preview after explicit user confirmation.

```json
{
  "preview_id": "preview_...",
  "confirmed_scope": "department",
  "target_department_id": "optional",
  "confirmation": {
    "confirmed": true,
    "confirmed_at": "ISO-8601"
  }
}
```

Expected response:

```json
{
  "artifact_id": "case_...",
  "version": "1.0.0",
  "scope": "department",
  "url": "https://registry.example/artifacts/case_..."
}
```

### `registry.update`

Create a new immutable version of an existing artifact. The preview and confirmation sequence still applies.

## Optional Tools

- `registry.get`
- `registry.rate`
- `registry.report`
- `registry.rollback`

## Error Handling

- `IDENTITY_REQUIRED`: establish an authenticated connector session.
- `SCOPE_DENIED`: show `allowed_scopes`; never invent additional identity claims.
- `VALIDATION_FAILED`: fix the draft and run preview again.
- `SENSITIVE_CONTENT`: sanitize and ask the user to reconfirm the changed preview.
- `VERSION_CONFLICT`: compare with the latest version and generate a new proposal.
