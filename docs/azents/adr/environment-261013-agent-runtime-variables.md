---
title: "Agent Runtime Environment Variables Decisions"
created: 2026-10-13
document_role: primary
document_type: adr
snapshot_id: environment-261013
tags: [runtime, agent, security, architecture]
---

# Agent Runtime Environment Variables Decisions

Snapshot: `environment-261013`.

## Authority and review boundary

[environment-261013/REQ](../requirements/environment-261013-agent-runtime-variables.md) records the additive per-Agent setting, Runtime Toolkit injection, reviewed UI, and requested PR. The implementation PR is the technical review boundary. The requester did not separately approve a complete technical Design; the choices below are recorded as implementation proposals, not retroactively asserted as approved decisions.

## D1. Keep encrypted settings on the Agent

References: `environment-261013/REQ-1`, `environment-261013/REQ-3`.

Proposed mechanism: retain one nullable encrypted JSON document on the Agent, using the existing CredentialCipher. The absence of a document means no configured variables. One Agent row lock serializes replacement and secret retention; the public read projection contains only names and presence metadata. No settings revision, history, cache, shared scope, or second credential authority is added.

Alternatives: a separate Agent-keyed table would add another lifetime/relationship for a setting that belongs entirely to the Agent; reusing Toolkit storage would contradict the independent Runtime setting requested here.

Risks: readers see a redacted list rather than value equality, so a concurrently changed value with the same name is retained by the explicit stored-reference operation. Full-list replacement intentionally follows normal settings semantics rather than introducing a new versioning or optimistic-lock contract.

## D2. Read current settings for each command

References: `environment-261013/REQ-2`, `environment-261013/REQ-4`.

Proposed mechanism: Runtime Toolkit reads the owning managed Runtime Agent's settings immediately before command launch, after current credential capability admission. Existing peer Toolkit environment collection stays unchanged. The new Agent mapping is merged last; it therefore takes precedence for duplicate names. This precedence was recommended to the requester but was not separately confirmed; it is called out for PR review.

Alternatives: peer Toolkit precedence weakens the direct Agent setting; rejection would make command launch fail when unrelated retained Toolkits contain the same name. Runner/container-global injection changes restart, lifetime, and Terminal behavior outside the requested scope.

Risks: removing an Agent setting can reveal a same-name retained Toolkit value. It removes only the new setting's contribution, not existing Toolkit credentials. This is intentional additive coexistence, not fallback to deprecated state. Settings read/decryption failures fail command preparation instead of silently launching without credentials.

## D3. Keep or replace secrets explicitly in whole-list updates

References: `environment-261013/REQ-1`, `environment-261013/REQ-3` and the approved redacted editor.

Proposed mechanism: each desired entry has a new name plus either an explicit stored-name reference or a replacement secret. Omitted entries are deleted. A retained secret can be renamed without plaintext retrieval; duplicate names, reused/missing references, invalid POSIX names, NUL values, and UTF-8 size limits are rejected. Empty replacement values are valid; the UI uses blank fields on existing entries to choose the stored-reference operation. The API does not overload null or absence to mean a secret value.

Alternatives: ordinary dictionary replacement would expose values on read or erase untouched secrets. Hidden empty-string or null fallback semantics cannot express retention and explicit replacement clearly. Per-entry persistent IDs would add identity solely for local form editing.

Security: request validation errors for these endpoints are sanitized so FastAPI cannot echo submitted credentials. Errors contain no values. Secret model representations are redacted. Logs, configuration status, lifecycle state, and Provider documents do not receive secret values.
