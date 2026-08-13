---
title: "Hierarchical Runtime Network Restriction Requirements"
created: 2026-08-12
updated: 2026-08-13
implemented: 2026-08-13
tags: [runtime, network, security, provider, workspace]
document_role: primary
document_type: requirements
snapshot_id: network-260812
---

# Hierarchical Runtime Network Restriction Requirements

- Snapshot: `network-260812`
- Document reference: `network-260812/REQ`

## Problem

Kubernetes Runtime Profiles currently support direct outbound network access constrained by allowed and denied IP CIDRs. Adding a mandatory HTTP proxy to the existing allowed destinations would leave the direct CIDR path available and allow Runtime processes to bypass the proxy. The product also lacks explicit network-access modes that let a Provider define the maximum outbound authority while allowing a Workspace to apply a stricter policy without weakening that Provider boundary.

Azents needs a hierarchical Runtime network restriction contract that preserves existing direct behavior, can require inspected HTTP traffic, can remove external network access, and fails closed whenever the selected Provider cannot enforce the effective restriction.

## Primary Actor

Workspace administrator.

## Primary Scenario

A Workspace administrator creates or updates a Workspace Runtime Profile that references a Provider-owned infrastructure Profile. The infrastructure Profile defines the maximum network authority available to the Runtime. The Workspace administrator preserves that authority or chooses a stricter network mode and additional restrictions. When an Agent uses the Profile, its Kubernetes Runtime receives exactly the effective network authority: direct outbound access within the inherited CIDR boundary, inspected proxy-only HTTP traffic within the inherited boundary, or no external network access. The Workspace cannot broaden the Provider Profile, and unavailable enforcement never falls back to a weaker mode.

## Supporting Scenarios

- A System Administrator defines a Kubernetes infrastructure Profile whose network mode and destination policy form the maximum authority available to referencing Workspaces.
- A Workspace changes a `direct` Profile to `proxy_required`; the Runtime loses direct external access while its dedicated proxy remains bounded by the Provider Profile's direct destination policy.
- A Workspace adds denied CIDRs while retaining `direct` mode.
- A Workspace narrows an unrestricted proxy domain policy to an explicit allowlist, reduces an existing allowlist, or adds denied domains.
- A Provider Profile selects `no_network`, causing every referencing Workspace Profile to retain `no_network`.
- A Runtime network mode or trust configuration change requires replacement before the new authority is reported applied, while narrower policy changes may converge without replacing unaffected resources.
- A Kubernetes Provider that cannot prove required network enforcement reports the Profile as unavailable.
- A Docker Provider remains usable for development with its supported direct behavior but does not claim unsupported proxy or external-network denial guarantees.

## Goals

- Define an explicit hierarchy of `direct`, `proxy_required`, and `no_network` Runtime network authority.
- Let Provider infrastructure Profiles establish the maximum network authority and Workspace Runtime Profiles preserve or reduce it.
- Preserve the Provider CIDR boundary when a Workspace changes direct access into mandatory proxy access.
- Make proxy bypass fail closed by removing direct external access from a proxy-required Runtime.
- Restrict proxy-required external communication to inspected HTTP, HTTPS, and WebSocket traffic.
- Preserve only the Platform communication required to operate an Azents Runtime in every supported mode.
- Make effective mode, protocol limitations, HTTPS inspection, compatibility, readiness, and failure visible to administrators and Runtime users.
- Keep unsupported Provider modes explicit and prevent automatic fallback to direct access.

## Non-Goals

- Guaranteeing that allowed destinations cannot be used to exfiltrate data.
- Providing content-aware data-loss prevention or inspecting application-level encrypted payloads inside allowed HTTP bodies.
- Providing a fully offline Runtime with no Runtime Control or transfer communication.
- Supporting arbitrary external TCP, SSH, database, UDP, QUIC, HTTP/3, DoH, or DoT traffic in `proxy_required` mode.
- Adding Agent-level network overrides below the selected Workspace Runtime Profile.
- Making Docker support for `proxy_required` or `no_network` a release blocker for the initial capability.
- Creating an Azents-owned per-request audit database, audit API, or traffic-log UI.
- Defining cluster-wide node security, CNI implementation, firewall administration, or log-retention policy.

## Requirements

### REQ-1. Hierarchical network authority

Runtime network authority must resolve from the selected Provider infrastructure Profile and the referencing Workspace Runtime Profile. The Workspace Profile may preserve or reduce the Provider authority but must never broaden it.

**Acceptance criteria**

- Network authority follows the restrictive order `direct` → `proxy_required` → `no_network`.
- A Provider `no_network` Profile resolves only to `no_network` for every Workspace.
- A Provider `proxy_required` Profile may remain `proxy_required` with stricter policy or become `no_network`.
- A Provider `direct` Profile may remain `direct` with stricter CIDR policy, become `proxy_required`, or become `no_network`.
- A lower layer cannot restore direct access, expand an allowed destination boundary, remove an inherited denial, or restore a protocol denied by the parent.
- Invalid expansions are rejected before they become desired Runtime configuration.

### REQ-2. Direct network mode

`direct` mode must preserve direct Runtime outbound behavior only within the effective Provider and Workspace CIDR boundary.

**Acceptance criteria**

- The Provider Profile defines the maximum direct CIDR authority.
- A Workspace retaining `direct` mode may narrow allowed CIDRs and add denied CIDRs.
- A Workspace cannot add an allowed CIDR outside an explicit Provider allowed boundary or remove an inherited denied CIDR.
- Required Platform communication remains available independently from customer-traffic CIDRs.
- Existing direct CIDR Profiles retain their direct behavior after migration unless an administrator explicitly selects a stricter mode.

### REQ-3. Mandatory proxy network mode

`proxy_required` mode must permit external Runtime traffic only through an inspected HTTP proxy path and must prevent direct external egress.

**Acceptance criteria**

- Runtime external HTTP, HTTPS, and WebSocket traffic can operate through the applicable proxy policy.
- Proxy-required Runtime environments expose `HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy`, and `https_proxy`, with all four names identifying the same applicable proxy endpoint so clients that support only one case continue to use the enforced path.
- Runtime direct external IP access is denied even when the Provider Profile permits those IPs in `direct` mode.
- When a Workspace changes a Provider `direct` policy to `proxy_required`, the inherited direct CIDR boundary remains the maximum external destination boundary of the proxy path.
- Removing proxy environment configuration, using a different HTTP client, resolving a destination IP directly, or opening a raw socket does not restore direct external access.
- Proxy unavailability, policy unavailability, or trust-configuration failure does not fall back to direct access.

### REQ-4. Proxy domain hierarchy

Proxy destination policy must distinguish unrestricted domain access from explicit allowlist access and must support restrictive Workspace policy composition.

**Acceptance criteria**

- Proxy domain authority follows the restrictive order `unrestricted` → `allowlist`.
- The policy state is explicit and does not derive unrestricted or deny-all behavior from an empty list.
- A Workspace may narrow Provider-unrestricted domain access to an allowlist.
- A Workspace may reduce an inherited allowlist and add denied domains.
- A Workspace cannot add domains outside an inherited Provider allowlist or remove an inherited domain denial.
- Domain checks do not permit a resolved destination to exceed the inherited CIDR boundary.

### REQ-5. Proxy protocol boundary

`proxy_required` mode must expose a clear and fail-closed protocol contract.

**Acceptance criteria**

- External HTTP, HTTPS, and WebSocket are the supported proxy-required protocols.
- External SSH, arbitrary TCP, database protocols, UDP, QUIC, HTTP/3, DoH, and DoT are denied.
- DNS is available only through the Platform-designated resolution path needed for the effective policy and mandatory Platform communication.
- Unsupported protocols do not receive a direct-network fallback.
- Product UI explains that non-HTTP protocols, including SSH Git URLs, do not work in this mode.

### REQ-6. HTTPS inspection and trust behavior

HTTPS traffic in `proxy_required` mode must be inspected through the proxy trust boundary without a transparent compatibility downgrade.

**Acceptance criteria**

- HTTPS requests use the Runtime proxy trust configuration and are subject to the effective destination policy.
- Certificate-pinned applications and applications that do not use the provided trust configuration may fail.
- TLS passthrough and direct HTTPS fallback are not automatically enabled when inspection fails.
- Product UI explains that HTTPS is inspected and that certificate pinning or custom trust stores may be incompatible.
- Sensitive trust authority that can issue interception certificates is not exposed to the Runtime workload.

### REQ-7. No external network mode

`no_network` mode must deny customer and external network access while preserving only communication required to operate the Azents Runtime.

**Acceptance criteria**

- Internet, private-network, cross-Runtime, proxy, and arbitrary TCP or UDP access are denied.
- Runtime Control, Runtime transfer, and the minimum Platform-designated name-resolution path remain available where required for ordinary Runtime operation.
- The UI identifies the mode as `No external network` and explains that required Azents Platform communication remains available.
- A `no_network` Runtime is not described as fully offline.

### REQ-8. Runtime-dedicated proxy lifecycle

A proxy-required Runtime must use a dedicated proxy execution boundary whose lifecycle and applied configuration remain synchronized with that logical Runtime.

**Acceptance criteria**

- One logical Runtime cannot use another Runtime's proxy authority.
- Starting or restarting a proxy-required Runtime does not report successful running state until its matching proxy and enforcement policy are ready for the same desired Runtime configuration.
- Stopping a Runtime removes its proxy execution resources while preserving ordinary Runtime Workspace storage.
- Reset and terminal deletion apply their existing storage semantics while removing obsolete proxy execution resources.
- Provider recovery can rediscover, verify, repair, or remove Runtime and proxy resources using bounded Runtime identity and current configuration evidence.
- A stale proxy from another Runtime generation cannot satisfy current readiness.

### REQ-9. Provider capability and fail-closed compatibility

A Provider may offer only network modes and enforcement behavior that it can prove on its execution substrate.

**Acceptance criteria**

- The initial Kubernetes Provider may advertise `direct`, `proxy_required`, and `no_network` when the Platform operator explicitly enables and attests the deployment support required for those modes.
- Best-effort deployment validation may warn about CNI, proxy, Service-address, or network-enforcement concerns without overriding the operator's capability enablement decision.
- A Provider that cannot apply or observe a selected Runtime's required resources makes that Runtime configuration unavailable or failed instead of silently applying a weaker mode.
- Docker may continue to support development-oriented direct execution without supporting the stricter modes.
- Docker's initial lack of strict modes does not block release of the Kubernetes capability.
- A strict Workspace Profile cannot be used through an incompatible Docker Provider by falling back to direct access.

### REQ-10. Policy application and readiness

Network policy changes must become authoritative through the existing desired and applied Runtime configuration boundary and must not be reported applied before their enforcement resources match.

**Acceptance criteria**

- A mode or trust change that affects Runtime process configuration remains pending until the required Runtime replacement completes.
- A policy-only change may converge without replacing unrelated resources only when the Provider can prove the resulting boundary is fully enforced.
- Runtime and proxy observations use current Runtime identity, desired generation, and configuration evidence.
- Missing, stale, broadened, or mismatched network enforcement resources prevent compliant readiness and follow bounded repair or recreation behavior.
- Tightening never temporarily restores a broader direct path during transition.

### REQ-11. User-visible explanation

Administrators and Runtime users must be able to understand the selected and effective network behavior and its important compatibility limits.

**Acceptance criteria**

- Profile editing and detail surfaces show the configured network mode and applicable CIDR or domain restrictions.
- Runtime status surfaces show the effective mode and whether its enforcement is pending, applied, unavailable, or incompatible.
- Proxy mode warns that only HTTP, HTTPS, and WebSocket are supported externally.
- Proxy mode warns that HTTPS is inspected and certificate pinning or custom trust stores may fail.
- No-external-network mode explains that required Azents Platform communication remains available.
- Errors distinguish unsupported Provider capability, invalid policy expansion, proxy readiness failure, and required Runtime recreation.

### REQ-12. Operational proxy logging

Proxy traffic diagnostics must integrate with ordinary workload logging without introducing a separate Azents traffic-audit product.

**Acceptance criteria**

- The selected proxy implementation emits access, denial, and operational diagnostics through its ordinary Pod stdout or stderr logs.
- The deployment's existing Kubernetes log collection and retention policy owns transport, storage, and search.
- Default proxy logging excludes authorization values, cookies, query strings, request and response bodies, and certificate private material.
- Azents does not require a per-request database record, audit API, or dedicated traffic-log UI for this capability.

## Fixed Constraints

- Provider infrastructure Profiles remain the maximum network authority; Workspace Runtime Profiles may only preserve or reduce it.
- Agent configuration does not add another network-policy override layer.
- Kubernetes NetworkPolicy or an equivalent Provider-external enforcement boundary, not proxy environment variables, is the anti-bypass authority.
- Multiple additive network policies must not restore a direct path that is absent from the effective mode.
- Mandatory Platform communication is independent from customer-controlled destination policy.
- Proxy inspection authority and private key material remain outside the untrusted Runtime workload.
- Existing direct Profiles do not silently change to proxy-required or no-external-network behavior.
- Unsupported or unavailable enforcement fails closed without mode fallback.

## Open Assumptions

- The Platform operator can determine whether the Kubernetes deployment's CNI and namespace ownership are suitable for strict network modes and accepts responsibility for enabling those capabilities despite non-blocking validation warnings.
- The selected proxy implementation supports inspected HTTP, HTTPS, and WebSocket traffic plus policy-safe operational logging.
- Exact domain-pattern syntax, proxy implementation, CA ownership lifecycle, DNS enforcement mechanism, and readiness protocol remain design decisions after Requirements confirmation.

## Confirmation

Confirmed by the requester on 2026-08-12 before ADR and design decisions began, and reconfirmed on 2026-08-12 after making strict-mode capability enablement operator-attested with non-blocking validation warnings.
