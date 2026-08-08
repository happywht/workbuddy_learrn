# ADR-012: Frontend Authentication Bootstrap

## Decision

The static WorkBuddy pages use `workbuddy-hub/auth.js` as the single client
authentication boundary. A deployment may inject `window.WORKBUDDY_ACCESS_TOKEN`
at runtime after its OIDC/SAML gateway has authenticated the user. The pages
send that value only as `Authorization: Bearer ...` and never accept a remote
`actor` query parameter or remote `X-Actor-Id` as identity.

`X-Actor-Id` and the `actor` query parameter remain available only when both the
page and Hub API hosts are local (`localhost`, `127.0.0.1`, or `::1`) and are
explicitly PoC behavior. A remote page without an injected Bearer token shows a
login-required state and lets the Hub return its normal `401` response.

## Boundary

This file does not implement an IdP, token refresh, or a browser token store.
Production must inject a short-lived token through the organization's approved
SSO shell or replace the bootstrap with its OIDC client. Tokens must not be
placed in URLs, committed files, or analytics payloads.
