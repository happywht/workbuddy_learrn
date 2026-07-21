---
name: workbuddy-publish-assistant
description: Package a confirmed successful task as a reusable WorkBuddy case or Skill, ask the user for personal, department, or organization scope, show a publish preview, and publish only after explicit confirmation.
version: 0.1.0
---

# WorkBuddy Publish Assistant

## Purpose

Turn a task that the user has already confirmed as useful into a reusable case or Skill package for WorkBuddy Hub. Do the packaging work yourself. Do not ask the user to write a tutorial or manually assemble metadata.

## Trigger

Use this Skill when either condition is true:

- The user asks to publish, share, package, contribute, or reuse a completed task.
- The user confirms that the current task result is useful and asks to make it available for later use.

Do not auto-publish merely because a task finished. Offer publication only when the result is demonstrably useful, and never create an external side effect without explicit confirmation.

## Non-negotiable Rules

1. There is no pre-publication human reviewer. Do not ask the user to nominate an approver.
2. Always generate a preview before publishing.
3. Always ask the user to choose exactly one scope: `personal`, `department`, or `organization`.
4. Always wait for explicit confirmation of the title, kind, scope, and sanitized preview.
5. Never infer or enlarge publication scope from seniority, department name, chat context, or file contents.
6. Never fabricate user identity or department membership. Use the identity context available to the current Agent/connector session. The registry service performs the final authorization check.
7. Never include access tokens, passwords, personal identifiers, confidential project names, client secrets, private URLs, or unredacted business data in a package.
8. Keep source evidence and formulas when they are necessary to reproduce a result, but replace sensitive values with schemas, synthetic examples, or redacted samples.
9. If the package cannot be made safe without losing its meaning, stop and explain what must be removed or replaced.
10. After publishing, return the registry URL, package ID, version, scope, and a short reuse instruction.

## Decide the Package Kind

Choose `case` when the value mainly comes from a specific business situation, example input, expected output, and prompt sequence.

Choose `skill` when the value is a repeatable capability with stable triggers, deterministic workflow steps, tool requirements, and output constraints.

Choose `case+skill` only when the case provides evidence and the Skill provides a reusable implementation. Publish them as linked artifacts, not as one ambiguous object.

## Workflow

### 1. Inspect the successful task

Collect from the current conversation and workspace:

- user goal and intended audience;
- input file types and required fields;
- successful prompt or instruction sequence;
- calculations, thresholds, tools, and connectors used;
- output files and acceptance criteria;
- corrections made during the task;
- known limitations and human review points.

Ask only for information that cannot be recovered from the task context.

### 2. Build a sanitized draft

Create a package draft using the structure in `references/package-format.md`.

Run these automatic checks before showing the preview:

- secret and credential scan;
- personal information scan;
- confidential project/client name scan;
- absolute local path scan;
- broken reference scan;
- required metadata and output-contract check;
- prompt dependency and external connector check.

Replace real records with schemas or synthetic samples. Record every replacement in `sanitization.changes`.

### 3. Show the preview

Show a concise preview containing:

- proposed title and one-sentence value;
- kind: `case`, `skill`, or linked `case+skill`;
- intended users and trigger phrases;
- input contract;
- workflow summary;
- output contract;
- required connectors or permissions;
- limitations and human review points;
- files included in the package;
- sanitization result;
- proposed semantic version.

Do not call a publish tool at this stage.

### 4. Ask for publication scope

Ask one focused question:

```text
请选择发布范围：
- 个人：仅自己可见和复用
- 部门：所在部门成员可见和复用
- 组织：当前组织范围可见和复用
```

If the Agent can resolve multiple departments, list the available department targets and ask the user to select one. Do not guess.

### 5. Obtain explicit confirmation

Repeat the final values:

```text
标题：...
类型：...
范围：...
目标部门：...（如适用）
版本：...
脱敏检查：通过 / 尚有问题
```

Ask the user to confirm publication. A vague acknowledgment from an earlier turn is not sufficient.

### 6. Publish

Call `registry.publish_preview` first. Resolve validation errors locally when possible.

After explicit confirmation, call `registry.publish` with the returned `preview_id` and the exact confirmed scope. Authentication must be provided by the connector/session, not embedded in package content.

If the server rejects the scope, preserve the draft and offer only the scopes returned in `allowed_scopes`. Do not retry with invented identity information.

### 7. Report the result

Return:

- package ID and version;
- publication scope;
- registry URL;
- what was sanitized;
- how another user should invoke or install it;
- how to report an issue or publish a new version.

## Update Existing Content

When a matching artifact already exists:

1. Compare the current task with the latest version.
2. Prefer a new version over a duplicate package.
3. Summarize the behavior change.
4. Use semantic versioning:
   - patch: clarification, prompt refinement, or non-breaking sample update;
   - minor: new optional behavior or output;
   - major: incompatible input, output, permission, or workflow change.
5. Call `registry.update` only after the same preview, scope, and confirmation sequence.

## Failure Handling

- API unavailable: keep the complete draft locally and return a retry instruction.
- Missing identity context: ask the current Agent environment to establish an authenticated registry session; do not ask the user to paste tokens into chat.
- Scope denied: show `allowed_scopes` and let the user choose again.
- Validation failed: fix the package and regenerate the preview.
- Sensitive content found: remove or replace it, show the changes, and request confirmation again.

## References

- `references/package-format.md`
- `references/publish-api.md`
- `schemas/package.schema.json`
- `schemas/publish-request.schema.json`
