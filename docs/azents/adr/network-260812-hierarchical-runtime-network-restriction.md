---
title: "Hierarchical Runtime Network Restriction"
created: 2026-08-12
tags: [runtime, network, security, provider, workspace, architecture]
document_role: primary
document_type: adr
snapshot_id: network-260812
---

# Hierarchical Runtime Network Restriction

- Snapshot: `network-260812`
- Document reference: `network-260812/ADR`
- Requirements: [Hierarchical Runtime Network Restriction Requirements](../requirements/network-260812-hierarchical-runtime-network-restriction.md) (`network-260812/REQ`)

## Decision Map

- [x] `network-260812/ADR-D1` — Introduce explicit new contract versions, preserve existing direct documents during rollout, and converge to one current version through later authoritative cleanup.
- [x] `network-260812/ADR-D2` — Use canonical exact-host and prefix-wildcard domain patterns with deny-final precedence.
- [x] `network-260812/ADR-D3` — Use a pinned mitmdump workload with an Azents policy addon.
- [x] `network-260812/ADR-D4` — Bind one persistent interception CA to the logical Runtime rather than to workload generations.
- [x] `network-260812/ADR-D5` — Remove DNS from strict Runtimes and inject observed mandatory Service addresses through the Runtime hosts file.
- [x] `network-260812/ADR-D6` — Keep all Runtime-dedicated proxy and CA resources under the Kubernetes Provider.
- [x] `network-260812/ADR-D7` — Let explicit operator attestation enable strict capabilities while deployment validation remains warning-only.
- [x] `network-260812/ADR-D8` — Replace only affected resources without policy hot reload and narrow authority before transition.

## Context

Kubernetes Runtime infrastructure Profiles currently carry one CIDR-based network policy, and Workspace Runtime Profiles may narrow it. The Kubernetes Provider composes the effective allowed and denied CIDRs with deployment-owned hard caps, creates one Runtime-specific NetworkPolicy, and can update that policy in place. The Profile models, Runtime configuration parser, OpenAPI clients, and Provider parser are strict and versioned. Docker does not implement the Workspace network restriction.

A proxy-only policy cannot be added as another Kubernetes NetworkPolicy beside the current direct policy because NetworkPolicy allow rules are additive. Mandatory proxy enforcement therefore requires a mode-specific complete egress policy, a dedicated proxy execution boundary, and exact lifecycle and configuration evidence. The current Kubernetes Provider resource boundary supports Pods, PVCs, and NetworkPolicies but not Services or ConfigMaps. Its current reconciliation evidence covers one Runtime NetworkPolicy rather than a complete Runtime-plus-proxy resource set.

The existing server MCP egress proxy is a shared Squid CONNECT proxy intended for server-side SSRF protection. It does not provide Runtime-specific TLS interception, hierarchical domain policy, or Runtime lifecycle ownership and is not a direct implementation of `network-260812/REQ`.

## Fixed and Derived Outcomes

The confirmed Requirements determine the following outcomes and they are not reopened as ADR choices:

- Provider infrastructure Profiles are the maximum network authority and Workspace Runtime Profiles only preserve or reduce it.
- Mode authority narrows through `direct` → `proxy_required` → `no_network`.
- Proxy domain authority narrows through `unrestricted` → `allowlist`.
- A Runtime in `proxy_required` has no direct external CIDR path; the inherited Provider CIDR boundary constrains proxy egress instead.
- One logical Runtime has one dedicated proxy workload synchronized with current Runtime configuration and lifecycle.
- Proxy-required external traffic supports inspected HTTP, HTTPS, and WebSocket only, with no direct, TLS-passthrough, or protocol fallback.
- `HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy`, and `https_proxy` identify the same dedicated proxy endpoint.
- `no_network` preserves only required Azents Platform communication.
- Kubernetes is the initial strict-mode Provider; Docker strict-mode support is not a release blocker and unsupported modes remain incompatible.
- Existing direct Profiles retain direct behavior until an administrator explicitly selects a stricter mode.
- Applied enforcement remains fenced by current Runtime identity, desired generation, configuration evidence, and the existing explicit recreation boundary.
- Proxy request diagnostics remain ordinary Pod logs rather than a new Azents traffic-audit product.

## Decisions

### network-260812/ADR-D1: Introduce explicit new contract versions and converge later

**Affected requirements:** `network-260812/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-9`, `REQ-10`

Kubernetes infrastructure Profile schema v3 introduces the explicit discriminated network modes `direct`, `proxy_required`, and `no_network`. Workspace Runtime Profile Policy schema v2 introduces the corresponding restrictive hierarchical override. Existing Kubernetes Profile schemas v1 and v2 retain their current CIDR-based direct meaning, and existing Workspace Policy v1 retains its current direct CIDR-restriction meaning during rollout.

The initial delivery does not rewrite stored legacy Profile documents, their digests, or current applied Runtime configuration. A new Workspace Policy v2 may narrow an existing direct infrastructure Profile when the bound Provider advertises the required capability, while an existing Workspace Policy v1 remains direct-only. Unknown or unsupported strict-mode contracts fail closed and never lower to direct execution.

The coexistence is transitional rather than a permanent compatibility architecture. After deployed Providers, stored Profiles, and product clients have moved to the new contracts, a later confirmed development snapshot will migrate remaining current data to one latest contract version and remove obsolete creation, editing, parsing, advertisement, and generated-client surfaces. This later cleanup is not silently performed by the current snapshot and requires its own migration and removal authority.

**Rejected:** Extending the meaning of existing schema versions would make one version identify multiple contracts and create mixed-version ambiguity. Migrating every stored Profile in the initial delivery would unnecessarily change digests and desired/applied configuration for Runtimes that retain direct behavior.

### network-260812/ADR-D2: Use canonical exact-host and prefix-wildcard domain patterns

**Affected requirements:** `network-260812/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`

Domain policy accepts only an exact canonical hostname such as `example.com` or a leading-label wildcard such as `*.example.com`. An exact hostname matches only that hostname. A wildcard matches one or more subordinate labels but does not match the apex, so a policy that permits both must state both patterns. General glob syntax, interior or partial wildcards, regular expressions, URLs, schemes, ports, paths, and query strings are invalid policy inputs.

Hostnames are canonicalized to lowercase IDNA ASCII with a trailing root dot removed before validation, comparison, persistence, hierarchy composition, and proxy evaluation. Policy subset checks are structural and deterministic: an exact host or narrower wildcard may be selected only within an inherited exact or wildcard authority. A Workspace cannot introduce a pattern outside the Provider authority.

The inherited CIDR boundary applies before domain authorization. Domain denial has final precedence over an otherwise allowed or unrestricted domain. Redirect targets are re-evaluated. CONNECT authority, TLS SNI, and the HTTP Host authority must remain canonically consistent; ambiguity or mismatch fails closed. In `allowlist` domain mode, destination IP literals are rejected because they have no authorized hostname; IP authority remains expressed through the CIDR boundary. An unrestricted proxy policy may accept an IP literal only when it remains within the inherited CIDR boundary and every other proxy restriction.

**Rejected:** Exact-host-only policy creates excessive operational churn for services with controlled subdomains. General glob or regular-expression policy makes hierarchical subset validation ambiguous, increases parser and denial-of-service risk, and can produce different interpretations between the server and proxy.

### network-260812/ADR-D3: Use a pinned mitmdump workload with an Azents policy addon

**Affected requirements:** `network-260812/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-8`, `REQ-12`

Each proxy-required Runtime uses an immutable-digest `mitmdump` image in regular forward-proxy mode. TLS interception, HTTP/1.1 and HTTP/2 forwarding, certificate generation, and WebSocket forwarding remain responsibilities of mitmproxy. A version-pinned Azents Python addon implements only the Azents-specific policy boundary: canonical effective-policy loading, policy digest verification, exact and prefix-wildcard domain authorization, deny-final precedence, CONNECT/SNI/Host consistency, redirect re-evaluation, fail-closed denial, bounded readiness evidence, and metadata-safe access and denial logs.

The proxy disables raw TCP forwarding, UDP and QUIC exposure, HTTP/3, TLS passthrough, `ignore_hosts`, insecure upstream TLS verification, management UI exposure, persistent flow dumps, and request or response body storage. NetworkPolicy remains the direct-egress anti-bypass authority; the addon cannot grant destinations outside the Provider CIDR boundary. The mitmproxy and addon versions are upgraded only with conformance coverage for the supported addon API and protocol matrix.

The existing shared MCP Squid proxy remains an independent server-side SSRF control. It is not reused as the Runtime proxy because it does not own Runtime lifecycle, TLS interception, hierarchical domain policy, or current Runtime configuration evidence.

**Rejected:** Squid SSL Bump can implement interception but would require a separate Runtime-specific configuration, helper, readiness, and policy translation surface while reusing little of the current MCP proxy. Envoy requires a substantially larger forward-proxy and dynamic-control design. A custom Azents TLS proxy would unnecessarily own security-sensitive protocol implementation.

### network-260812/ADR-D4: Bind one persistent interception CA to the logical Runtime

**Affected requirements:** `network-260812/REQ-6`, `REQ-8`, `REQ-10`

Each logical Runtime owns one persistent MITM interception CA whose identity is independent from desired generation, configuration sequence, Proxy Pod identity, and Runtime Pod identity. The CA remains stable through stop, start, restart, reset, Provider restart, proxy replacement, Runtime replacement, and policy change. Terminal Runtime deletion removes it. The proxy receives the CA private key and certificate read-only, while the untrusted Runtime receives only the public CA certificate through a separate read-only trust path.

The Provider does not report proxy-required enforcement applied unless the Runtime trust configuration and proxy report the same CA fingerprint together with current Runtime configuration evidence. Missing, unreadable, or mismatched CA state fails closed. An existing Runtime whose CA state is missing is not silently assigned a replacement CA under its current applied configuration; recovery creates explicit new desired configuration and synchronously replaces affected proxy and Runtime trust state.

CA rotation is an explicit staged operation rather than an automatic generation side effect. The Runtime first adopts a trust bundle containing the current and next public CAs while the proxy continues signing with the current CA. Only after that trust state is acknowledged may the proxy switch to the next private key. Removal of the old CA is a later confirmed cleanup step. Automatic periodic rotation and a general CA-management product surface are outside the initial delivery.

The component that owns CA creation, durable Secret storage, deletion, and narrow access authority is resolved with the proxy-resource ownership decision in `network-260812/ADR-D6`; that choice cannot change the logical-Runtime lifetime or private-key exposure boundary accepted here.

**Rejected:** A deployment-wide shared CA makes one proxy compromise affect every proxy-required Runtime. A per-Proxy-generation ephemeral CA couples ordinary workload churn to trust replacement and cannot reliably prevent partial-generation mismatch. An external CA service introduces a separate stateful security service beyond the initial product need.

### network-260812/ADR-D5: Remove DNS from strict Runtimes and inject mandatory Service addresses

**Affected requirements:** `network-260812/REQ-3`, `REQ-5`, `REQ-7`, `REQ-8`, `REQ-9`, `REQ-10`

Runtimes in `proxy_required` or `no_network` mode receive no DNS egress, including no direct CoreDNS access. Their Pod resolver configuration fails external lookup quickly, while Provider-generated hosts-file entries map only the observed mandatory Runtime Control, Runtime transfer, and Runtime-dedicated proxy Service hostnames to their current ClusterIP addresses. The existing hostnames remain in application endpoint configuration so TLS DNS-name validation is preserved; only name resolution changes. Direct mode retains its existing cluster DNS behavior.

The Runtime-dedicated proxy, not the Runtime, resolves external destination hostnames. The proxy may access cluster DNS, but it authorizes the canonical hostname first, evaluates all resolved A and AAAA addresses against the inherited Provider CIDR boundary, and verifies the actual selected upstream address before connection. Runtime NetworkPolicy denies direct DNS, DoH, DoT, DoQ, and arbitrary resolver access.

A Kubernetes deployment advertises strict network modes only when the Provider can observe stable ClusterIP Services for every mandatory Runtime endpoint and its dedicated proxy. A missing, changed, headless, external-name, or otherwise non-deterministically addressable mandatory Service prevents compliant readiness or requires explicit Runtime replacement with refreshed hosts-file evidence. There is no fallback to general DNS. The initial design adds no separate DNS Deployment and no DNS listener to Runtime Control or the Provider process.

**Rejected:** Direct CoreDNS access leaves a DNS exfiltration channel that contradicts proxy-only and no-external-network claims. A shared restricted DNS gateway adds another operational component. A Runtime-specific DNS workload adds per-Runtime lifecycle and readiness cost without benefit once mandatory endpoints can be resolved from observed Services.

### network-260812/ADR-D6: Keep Runtime proxy and CA resources under the Kubernetes Provider

**Affected requirements:** `network-260812/REQ-3`, `REQ-6`, `REQ-8`, `REQ-9`, `REQ-10`, `REQ-12`

The Kubernetes Provider remains the single substrate reconciliation authority for a logical Runtime and directly owns its Runtime Pod, Workspace PVC, Runtime NetworkPolicy, persistent Runtime CA Secret, canonical proxy-policy ConfigMap, proxy Service, proxy Pod, and proxy ingress and egress NetworkPolicies. No new proxy controller, CRD, or Runtime Control Kubernetes-resource path is introduced.

The Provider's workload-namespace Role adds CRUD for Services, ConfigMaps, and Secrets. The Provider deterministically owns resource names and labels; Profile or Workspace input cannot select Kubernetes object names, mounts, Secret keys, or raw manifests. The CA Secret is retained through stop, restart, reset, Provider restart, and workload replacement and is removed only during terminal Runtime deletion. The Runtime Pod mounts only the public CA certificate, while the proxy Pod mounts the private key and certificate read-only. Canonical proxy policy is delivered separately through a ConfigMap and is identified by the current Runtime configuration digest. Private key and sensitive policy material never enter Control commands, Provider reports, diagnostics, or logs.

Provider recovery lists and reconciles only resources carrying its exact managed-by, Provider, Runtime, role, and ownership labels. It neither adopts nor deletes unrelated resources. The workload namespace is an explicit Provider-controlled execution namespace and must not contain shared application credentials or unrelated high-value Secrets; the Provider already has authority to create Pods in that namespace, so Secret isolation from the Provider cannot be claimed there.

**Rejected:** Splitting CA state into Runtime Control would make Control aware of Provider-native Kubernetes resources and divide lifecycle ownership. A dedicated proxy controller would add another reconciliation authority, Deployment, ServiceAccount, protocol or CRD, failure domain, and ordering boundary without a confirmed product need.

### network-260812/ADR-D7: Use explicit operator attestation with warning-only validation

**Affected requirements:** `network-260812/REQ-9`, `REQ-10`, `REQ-11`

The Platform operator explicitly enables and attests Kubernetes deployment support for `proxy_required` and `no_network`. That deployment setting authorizes the Provider to advertise the corresponding Profile capabilities. Provider startup and operational diagnostics perform best-effort checks for expected CNI and NetworkPolicy configuration, namespace policy ownership, required RBAC, immutable proxy artifacts, and stable mandatory Service addresses, but discovered concerns produce structured warnings and safe Admin diagnostics rather than suppressing an operator-enabled capability.

Azents does not claim that capability advertisement proves CNI data-plane enforcement or absence of additive third-party NetworkPolicies. Product and deployment documentation state that strict-mode security depends on operator-owned CNI enforcement, namespace ownership, and prevention of conflicting policies. Deterministic and live negative tests remain required delivery evidence, but they do not become runtime capability authority.

Individual Runtime application still fails closed. Failure to create, read, or reconcile its proxy, CA, Service, hosts mapping, ConfigMap, or NetworkPolicies; stale configuration evidence; CA or policy-digest mismatch; or proxy readiness failure prevents compliant application and never falls back to direct networking. Stop and terminal deletion remain available for authority reduction and cleanup.

**Rejected:** Automatically gating capability advertisement on active qualification would let transient test infrastructure or environmental reachability remove current Provider capability and make Profiles unavailable without an operator decision. Advertising strict capability unconditionally without explicit operator enablement would conceal the deployment responsibility.

### network-260812/ADR-D8: Replace affected resources without policy hot reload and narrow first

**Affected requirements:** `network-260812/REQ-1`, `REQ-3`, `REQ-6`, `REQ-7`, `REQ-8`, `REQ-10`, `REQ-11`

Policy hot reload is not part of the initial implementation. CIDR-only changes update the applicable Runtime or proxy NetworkPolicy in place. Domain-policy or immutable proxy artifact changes create a new canonical ConfigMap and replace only the proxy Pod while retaining the logical Runtime's CA Secret and stable proxy Service. Mode, CA trust, or mandatory hosts-file changes replace the Runtime Pod because its environment, mounted trust, or name-resolution state changes. Explicit CA rotation follows the staged trust procedure accepted by `network-260812/ADR-D4`.

Authority-reducing transitions remove the broader path before completing replacement. `direct` to `proxy_required` first prepares and verifies the proxy, then narrows Runtime egress to proxy-only before replacing the Runtime with proxy environment and trust. `proxy_required` to `no_network` removes Runtime proxy reachability before replacing the Runtime and deleting obsolete proxy execution resources. Temporary loss of external connectivity is acceptable; temporary retention or restoration of a broader path is not. No transition falls back to direct execution.

Provider observation treats missing, stale, broadened, or mismatched Runtime and proxy policies, proxy Pod readiness, policy digest, CA fingerprint, Service selector or ClusterIP, hosts-file input, and current configuration evidence as non-compliant. It repairs NetworkPolicy drift in place, replaces only stale proxy resources when CA and Runtime environment remain valid, and reports explicit recreation required when Runtime environment, trust, or hosts input must change. Workspace PVC state remains outside these replacements.

**Rejected:** Addon policy hot reload adds a second application protocol, ambiguous ConfigMap propagation and acknowledgement timing, and a risk that a stale broader policy remains active while being reported current. Recreating every Runtime for every policy edit creates unnecessary disruption when the enforced boundary can be changed in a narrower resource set.
