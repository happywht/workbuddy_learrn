# Package Format

The root `SKILL.md` is the Agent-readable entry point. All other files support discovery, portability, validation, examples, and maintenance.

```text
package/
├─ SKILL.md
├─ manifest.json
├─ README.md
├─ case.json                 # required for a case; optional for a pure Skill
├─ prompts/                  # reusable prompts and variants
├─ references/               # business rules, field dictionaries, formulas
├─ examples/                 # synthetic or fully sanitized input/output
├─ assets/                   # images or templates safe to distribute
├─ scripts/                  # optional deterministic helpers
├─ tests/                    # optional fixtures and acceptance checks
└─ CHANGELOG.md
```

## Required Manifest Fields

```json
{
  "id": "stable-lowercase-id",
  "name": "Human readable name",
  "version": "1.0.0",
  "kind": "case",
  "summary": "One sentence value",
  "scope": "department",
  "tags": ["project", "report"],
  "inputs": [],
  "outputs": [],
  "permissions": [],
  "human_review": [],
  "sanitization": {
    "status": "passed",
    "changes": []
  }
}
```

Allowed `kind` values are `case` and `skill`. Linked case and Skill artifacts use `links`, not a third package type.

## SKILL.md Requirements

A reusable Skill must state:

- purpose and trigger conditions;
- required tools and permissions;
- input contract;
- ordered workflow;
- output contract;
- failure behavior;
- privacy and security constraints;
- human review points;
- references used by the workflow.

Do not include raw secrets, tokens, personal identifiers, confidential records, machine-specific absolute paths, or inaccessible internal links.

## Case Requirements

A case must state:

- business goal and target user;
- starting material and required fields;
- original pain point;
- prompt or Agent instruction;
- important reasoning rules and formulas;
- expected output and acceptance criteria;
- synthetic example or schema;
- known limitations and review points;
- linked Skill, if one exists.
