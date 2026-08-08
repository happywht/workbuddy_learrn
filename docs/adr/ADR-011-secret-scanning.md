# ADR-011: Repository Secret Scanning

## Decision

Run `tools/secret_scan.py` in local checks and on every push/pull request. The
scanner uses the Git file list by default, skips binary/large/generated files,
recognizes private-key and common token prefixes, and checks credential-shaped
assignments without printing matched values.

Example placeholders in `.env.example`, deployment documentation, and tests are
allowed only when they are clearly empty, parameterized, or named as examples.
Real credentials must be supplied through a Secret Manager or process
environment and must never be committed.

## Scope and limits

This is a deterministic leak-prevention gate, not a substitute for credential
rotation, history review, dependency scanning, or a provider-side secret
scanner. The existing ignored `配置服务器.txt` remains outside the Git file
list; it must still be rotated and reviewed manually before production use.
