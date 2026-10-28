# Agent-scoped inference authority contracts

Shared types for the private Azents authority channel. This package is not an
inference API, provider SDK, credential store, or authorization implementation.
It has no dependency on the Azents application or LiteLLM.

- `target.InferenceTarget` hashes the exact stored label, integration ID, and model
  identifier using UTF-8 compact JSON. It does not normalize provider identifiers,
  encode candidate position, or grant authority.
- `authority` contains closed list/resolve and privileged issuance payloads plus
  a discriminated provider credential union. Refresh tokens and arbitrary SDK
  kwargs are intentionally absent.
- `protected_json()` explicitly serializes sensitive values for the authenticated
  encrypted authority transport. Ordinary Pydantic serialization/repr masks them.
  Never log the protected serialization, credentials, or request body. This is
  representation hygiene, not a substitute for complete logging/tracing audits.
- Invalid payload diagnostics hide input in exception text. At ingress never log
  `ValidationError.errors()` or `.json()` with their defaults: use
  `errors(include_input=False, include_context=False)` or a fixed safe category.
  Pydantic's structured error APIs can otherwise retain raw rejected secrets.

Consumers must still authenticate the service and Agent, revalidate current
configuration, and supply only server-approved credential material. Constructing
a valid DTO is not proof of access. The initial package defines route/credential
identity only; implementation of candidate controls and provider capabilities
belongs to the authority/Proxy integration, not a parallel settings store.
