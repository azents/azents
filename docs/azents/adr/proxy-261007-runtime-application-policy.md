---
title: "Runtime Application Policy Ownership Decisions"
created: 2026-10-07
tags: [runtime, security, gateway]
document_role: primary
document_type: adr
snapshot_id: proxy-261007
---

# Runtime Application Policy Ownership Decisions

- Snapshot: `proxy-261007`
- Requirements: [proxy-261007/REQ](../requirements/proxy-261007-runtime-application-policy.md)

## ADR-D1. Separate application policy from platform access control

**Accepted by the requester on 2026-10-07.**

For `proxy-261007/REQ-1` and `REQ-2`, remove application Origin/Fetch Metadata
admission gates, Gateway-owned CORS preflight synthesis, and forced application
security/cache response headers. Runtime applications own their CSRF/CORS and
response policy. Platform identity, membership/service authority, exposure,
generation fencing, credential isolation, transport limits, and platform-owned
authentication-route security remain unchanged under `proxy-261007/REQ-3`.

### Alternatives

- **Retain Gateway CSRF/CORS and adjust Referrer-Policy:** rejected because it
  preserves the platform's application-policy responsibility and still prevents
  authenticated non-browser/external-origin development requests.
- **Allow every `Origin: null` request only:** rejected as an incomplete
  special case that does not establish the approved ownership boundary.
- **Make services anonymous or bypass OPTIONS authentication:** rejected as
  outside the confirmed platform access constraints.
- **Transparent authenticated application policy:** accepted.

### Consequences and risks

- An application without CSRF protection can accept state-changing requests
  initiated by another site whenever browser cookie rules send a valid identity.
  This is a consequence of the approved application-owned policy, not a claim
  that temporary exposure eliminates the risk.
- Application cache policy can permit cached responses to outlive service
  exposure. Exposure controls network admission, not already-downloaded content.
- Cross-origin browser preflight remains unauthenticated by browser design and
  therefore cannot reach an identity-protected application. Anonymous preflight
  support requires a separate authorized change.
- Existing Service Worker isolation remains to protect platform exposure and
  browser identity lifecycle; it is not application CSRF policy.
- No migration, mode flag, protocol compatibility path, or new configuration is
  introduced. Rollback is deployment of the previous Gateway implementation.
