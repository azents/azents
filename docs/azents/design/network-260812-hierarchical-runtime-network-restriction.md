---
title: "Hierarchical Runtime Network Restriction Design"
created: 2026-08-12
updated: 2026-08-13
implemented: 2026-08-13
tags: [runtime, network, security, provider, workspace, kubernetes, frontend, testenv]
document_role: primary
document_type: design
snapshot_id: network-260812
---

# Hierarchical Runtime Network Restriction Design

- Snapshot: `network-260812`
- Document reference: `network-260812/DESIGN`
- Requirements: [Hierarchical Runtime Network Restriction Requirements](../requirements/network-260812-hierarchical-runtime-network-restriction.md) (`network-260812/REQ`)
- ADR: [Hierarchical Runtime Network Restriction](../adr/network-260812-hierarchical-runtime-network-restriction.md) (`network-260812/ADR`)

## Current Behavior and Gaps

Kubernetes Pod Profile schemas v1 and v2 currently contain one CIDR-based
`network_policy`. Workspace Runtime Profile Policy v1 may narrow those CIDRs. The
resolver writes one canonical desired Runtime configuration, the Kubernetes Provider
creates one complete Runtime NetworkPolicy, and a current `OBSERVE` completion may
report one `network_policy` reconciliation result. Runtime Control may then dispatch
one fenced `UPDATE_CONFIGURATION` without recreating the Runtime Pod.

The current implementation has these gaps against `network-260812/REQ`:

1. Profile contracts do not represent `direct`, `proxy_required`, or `no_network`.
2. The Runtime Pod always receives DNS and direct customer egress permitted by its
   CIDR policy.
3. The Kubernetes Provider models only Pods, PVCs, and NetworkPolicies. It cannot
   own the required proxy Service, policy ConfigMap, CA Secret, trust mount, or
   mandatory hosts-file inputs.
4. The Runner image has the operating-system CA package but no custom interception
   CA bootstrap or inherited child-process trust bundle.
5. Provider observation and in-place repair cover one Runtime NetworkPolicy rather
   than the complete Runtime-plus-proxy enforcement bundle.
6. Provider capability advertisement has no strict-mode operator attestation or
   structured deployment-warning projection.
7. Public Runtime status exposes desired/applied configuration identity but not a
   bounded effective network-mode projection.
8. Profile web surfaces edit CIDRs only, and the existing E2E path is primarily the
   Docker Provider, which cannot prove Kubernetes proxy bypass prevention or external
   network denial.

The existing shared MCP Squid proxy is retained unchanged. It is server-owned SSRF
infrastructure and has no Runtime-specific interception CA, policy, lifecycle, or
configuration evidence.

## Design Overview

Kubernetes Pod Profile schema v3 and Workspace Runtime Profile Policy schema v2 add
explicit hierarchical network contracts. Legacy Profile and Policy documents remain
stored and retain direct behavior. A Policy v2 resolution always produces an
effective Kubernetes Pod Profile v3, including when its source infrastructure
Profile is legacy v1 or v2.

For `proxy_required`, the Kubernetes Provider creates one Runtime-dedicated
mitmdump Pod, stable ClusterIP Service, canonical policy ConfigMap, logical-Runtime
CA Secret, proxy ingress and egress NetworkPolicies, and one complete Runtime
NetworkPolicy. The Runtime has no DNS egress and can reach only required Platform
workloads and its own proxy. The Provider observes mandatory Service ClusterIPs and
injects exact host mappings into the Runtime Pod. The Runtime mounts only the public
CA certificate and prepares a child-process trust bundle; the proxy alone mounts the
private CA material.

For `no_network`, the Runtime has no DNS, proxy, customer CIDR, cross-Runtime, or
arbitrary transport access. It retains only the Runtime Control and transfer path
needed for ordinary Azents operation.

The existing desired/applied configuration state remains the product source of
truth. Kubernetes Provider protocol v3 replaces the narrow actionable
`network_policy` observation with one aggregate `network_enforcement` observation.
That result is `in_sync` only when every mode-required resource and readiness fence
matches the current Runtime identity and configuration evidence. Runtime Control
continues to own fenced repair dispatch and does not persist Kubernetes resource
inventory or drift history.

## Profile and Policy Contracts

### Kubernetes Pod Profile schema v3

Schema v3 retains the existing Runner resources, Workspace volume, service account,
scheduling, and optional DinD modules. It replaces `network_policy` with one
strictly discriminated `network_access` module:

- `direct`
  - `mode: "direct"`
  - explicit `allowed_cidrs` and `denied_cidrs`;
- `proxy_required`
  - `mode: "proxy_required"`;
  - explicit destination `allowed_cidrs` and `denied_cidrs`;
  - domain policy with explicit `mode: "unrestricted"` or `mode: "allowlist"`;
  - explicit allowed and denied domain-pattern arrays; and
- `no_network`
  - `mode: "no_network"` with no customer destination fields.

An empty CIDR allowlist retains the existing meaning of unrestricted IP authority
before inherited denials and deployment hard caps. Domain policy never infers its
mode from an empty list. `allowlist` with an empty allowed list is explicit deny-all.
Unknown fields and invalid mode-specific fields are rejected.

Infrastructure Profiles v1 and v2 remain direct CIDR contracts. Their stored JSON,
schema version, digest, and existing applied Runtime documents are not rewritten.

### Workspace Runtime Profile Policy schema v2

Policy v2 contains one explicit `network_restriction` variant:

- `inherit` preserves the Provider infrastructure Profile network authority;
- `direct` is valid only below Provider `direct` and may narrow allowed CIDRs and add
  denied CIDRs;
- `proxy_required` is valid below Provider `direct` or `proxy_required`, may narrow
  destination CIDRs, and supplies an explicit domain mode and restrictions; and
- `no_network` is valid below every Provider mode.

Composition validates the mode order before persistence of a ready desired
configuration. CIDR subset checks use canonical IPv4/IPv6 network containment.
Domain subset checks use the canonical pattern rules from `network-260812/ADR-D2`.
Inherited denials are unioned and cannot be removed. An invalid expansion returns a
bounded policy error and never becomes desired Runtime configuration.

Policy v1 remains direct-only. A Policy v2 may reference a legacy Kubernetes v1 or
v2 infrastructure Profile and narrow its direct authority into any permitted mode.
Docker accepts Policy v1 direct behavior only and reports Policy v2 strict modes as
incompatible rather than lowering them to direct.

### Canonical domain policy

Hostnames are converted to lowercase IDNA ASCII and have one trailing root dot
removed. Inputs accept only exact hostnames and leading-label wildcards such as
`*.example.com`. Exact hosts do not match descendants; wildcard patterns match one
or more descendant labels and not the apex.

The server uses the same canonical model for persistence, hierarchy checks, digest
calculation, API responses, and test fixtures. The proxy addon uses the same test
vectors but remains independently implemented inside the proxy image. Denials are
final. Redirect targets are re-evaluated. CONNECT authority, TLS SNI, and HTTP Host
authority must agree after canonicalization. Ambiguous or absent authority fails
closed. IP literals are rejected in allowlist mode and remain CIDR-bounded in
unrestricted mode.

## Provider Capability and Deployment Configuration

The Kubernetes Provider advertises Pod Profile schema versions 1, 2, and 3. Schema
v3 mode compatibility requires mode-specific capabilities:

- direct: the existing Runtime NetworkPolicy capability;
- proxy-required: dedicated inspected HTTP proxy and aggregate network-enforcement
  reconciliation capabilities; and
- no-network: external-network denial and aggregate network-enforcement
  reconciliation capabilities.

Helm exposes independent, default-disabled operator attestations for
`proxyRequired` and `noNetwork`. Enabling one causes the Provider to advertise the
matching capability. Proxy-required enablement additionally requires immutable
digest references for the Runtime proxy image and bundled Azents addon. The image
contains pinned mitmproxy and addon versions; Profile or Workspace input cannot
select them.

Provider startup performs best-effort checks for:

- required API discovery and RBAC for Pods, PVCs, Services, ConfigMaps, Secrets, and
  NetworkPolicies;
- stable mandatory ClusterIP Services and expected endpoint hostnames;
- expected namespace identity and the chart-owned default-deny policy;
- apparent CNI/NetworkPolicy support where it can be discovered safely;
- unexpected NetworkPolicies selecting Provider-managed Runtime or proxy Pods; and
- immutable proxy artifact configuration.

These checks emit structured warning codes, safe metadata, and English logs. Their
current snapshot is carried by the Provider v3 operational-diagnostics payload,
fenced to the authenticated connection generation, and stored on that durable
Provider connection row rather than in the capability contract. Registration
creates the initial snapshot, and Provider heartbeat may replace it after a later
periodic check. Admin Provider detail reads only the active current connection
snapshot. When no current connection exists, diagnostics are unavailable; an older
connection row is never reused as current evidence by a new generation.

Warning changes do not change the capability digest, enqueue Profile reconciliation,
or suppress an operator-enabled capability. Product and deployment documentation
state that the operator owns CNI enforcement, the dedicated workload namespace, and
prevention of additive policies.

A Runtime-specific failure remains authoritative regardless of attestation. Failure
to create, read, compare, or reconcile any required resource prevents a matching
Provider acknowledgement and never selects direct networking.

## Kubernetes Resource Ownership

The Kubernetes Provider is the sole Kubernetes reconciliation authority for the
following logical-Runtime resource set:

| Resource | Lifetime | Purpose |
| --- | --- | --- |
| Runtime Pod | Running incarnation | Runner and optional DinD workload |
| Workspace PVC | Existing Runtime storage lifecycle | Durable Agent Workspace |
| Runtime NetworkPolicy | Running incarnation | Complete Runtime ingress/egress boundary |
| Runtime CA Secret | Logical Runtime | Persistent interception private key and public certificate |
| Proxy policy ConfigMap | Active proxy policy revision | Canonical policy and expected evidence |
| Proxy Service | Running proxy-required lifecycle | Stable ClusterIP endpoint across in-place proxy Pod replacement |
| Proxy Pod | Running proxy-required incarnation | Inspected forward proxy |
| Proxy ingress NetworkPolicy | Running proxy-required incarnation | Runtime-to-own-proxy access only |
| Proxy egress NetworkPolicy | Running proxy-required incarnation | DNS plus inherited CIDR boundary |

Resource names are derived only from the validated logical Runtime ID and fixed role
suffixes. Labels include exact managed-by, Provider ID, Runtime ID, Workspace ID,
Agent ID, resource role, desired generation where applicable, and configuration
management identity. Annotations carry only non-secret configuration sequence,
digest, policy digest, CA fingerprint, and immutable artifact digest as applicable.

Recovery lists resources only by exact Provider ownership labels and validates every
Runtime ID before reporting or cleanup. It does not adopt a name-only match, a
foreign managed-by value, or an unrelated Secret, ConfigMap, Service, Pod, PVC, or
NetworkPolicy. Terminal deletion removes only the exact owned set. The Provider
workload namespace is documented as a dedicated execution namespace and must not
contain unrelated high-value shared Secrets.

The Provider package adds typed Kubernetes models, parsers, manifests, and REST
methods for Services, ConfigMaps, Secrets, Secret/ConfigMap volumes, `hostAliases`,
and strict Pod DNS configuration. The Helm workload-namespace Role adds only the
CRUD, list, and watch verbs needed for exact Provider-owned resources. A separate
read-only Role in each configured mandatory-Service namespace grants `get` only for
the explicitly named Platform Services; the initial chart binds the Provider
ServiceAccount to the `runtime-control` Service in the server namespace. It does not
receive cluster-wide Service discovery. No CRD, controller, Runtime Control
Kubernetes client, or second reconciliation process is introduced.

## Interception CA and Runtime Trust

On the first proxy-required preparation for a logical Runtime, the Provider creates
one CA using a versioned cryptographic profile implemented with a narrowly scoped
`cryptography` dependency in the Kubernetes Provider package. The Secret contains a
combined private-key/certificate value for mitmproxy and a separate public
certificate value. The Runtime Pod volume selects only the public value; the proxy
Pod volume selects the private value read-only.

An existing current CA Secret is never silently regenerated. Missing CA state for a
previously applied proxy-required Runtime, malformed key material, key/certificate
mismatch, unexpected subject identity, or fingerprint mismatch is a fail-closed
configuration failure. Initial creation may generate the CA only when no prior
applied CA identity exists. Terminal Runtime deletion removes the Secret. Stop,
start, restart, reset, Runtime Pod replacement, proxy replacement, policy change,
and Provider restart retain it.

The Runner receives a fixed read-only public-CA path. During startup it validates the
PEM certificate, appends it to the Runner image's own operating-system CA bundle in
a Runtime-incarnation writable file, and exports that exact bundle through standard
child-process trust variables, including `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`,
`CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`, and `NODE_EXTRA_CA_CERTS`. It does not replace
the image's public roots. Proxy-required child processes also receive
`HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy`, and `https_proxy`, all with the same
proxy Service hostname and port. Direct and no-network modes receive none of these
proxy or interception-trust values.

Runner startup failure to prepare the bundle prevents Runner readiness. Applications
that ignore these variables, use a private trust store, or pin certificates may
fail; the system does not enable TLS passthrough or direct fallback.

Automatic CA rotation and a general CA-management UI remain outside this delivery.
A later explicit rotation mechanism must use the accepted two-trust staged sequence:
Runtime trust current-plus-next, proxy signing switch after acknowledgement, then a
separate old-trust cleanup. The initial implementation records certificate expiry
and fingerprint in safe Provider diagnostics so operators can plan that explicit
operation.

## Proxy Workload and Policy Enforcement

A dedicated Runtime proxy image contains pinned mitmdump and the Azents policy
addon. The proxy listens only on its forward-proxy port and a loopback-only internal
readiness path. It exposes no management UI or transparent-proxy listener.

The canonical ConfigMap contains:

- schema version;
- Runtime ID and current configuration sequence/digest;
- domain policy mode and canonical allow/deny patterns;
- canonical inherited allowed and denied CIDRs;
- expected CA fingerprint; and
- proxy image/addon artifact digest.

The addon verifies the canonical policy digest before becoming ready. It authorizes
the canonical hostname before resolution, evaluates every resolved A and AAAA
address against the inherited CIDR boundary, and verifies the selected upstream
address immediately before connection. It rechecks redirects and Host/SNI/CONNECT
consistency. It disables raw TCP forwarding, UDP, QUIC, HTTP/3, TLS passthrough,
`ignore_hosts`, insecure upstream TLS, flow persistence, and request/response body
storage.

The proxy Pod readiness probe succeeds only when the running addon has loaded the
expected configuration sequence, policy digest, CA fingerprint, and artifact digest.
The Provider treats ordinary Pod Ready plus exact Pod/ConfigMap/Secret metadata as
the proxy's bounded application acknowledgement.

Proxy logs go to stdout/stderr. Access and denial records contain bounded timestamp,
Runtime identity, decision, canonical destination host, destination port, selected
IP classification, protocol class, and policy digest. They exclude authorization
values, cookies, query strings, bodies, certificate private material, and raw policy
or credential documents. Existing Kubernetes collection and retention own storage
and search.

## DNS, Mandatory Services, and NetworkPolicy

Direct mode retains cluster DNS and its existing Runtime Control plus customer CIDR
egress behavior.

Proxy-required and no-network Runtime Pods use `dnsPolicy: None` with a local
non-listening resolver target and bounded resolver attempts so non-hosts lookups fail
quickly without leaving the Pod. The Runtime NetworkPolicy contains no DNS rule.
Provider-generated `hostAliases` map only exact mandatory endpoint hostnames to
observed ClusterIP addresses:

- the Service backing Runtime Control and Runtime transfer; and
- for proxy-required mode, the Runtime-dedicated proxy Service.

The Provider receives explicit deployment-owned mandatory Service references rather
than deriving Kubernetes authority from an arbitrary Runtime endpoint string. It
verifies that command endpoint hostnames correspond to the configured references and
observes each Service as non-headless, non-ExternalName, stable ClusterIP. The
current chart maps both Runtime Control and transfer endpoints to the one
`runtime-control` Service; the configuration remains a list so a future deployment
may use separate stable Services without changing the Runtime contract.

Strict Runtime application fails when a mandatory Service is missing or unsuitable.
A changed ClusterIP or required hostname mapping classifies the Runtime configuration
as requiring recreation. There is no general-DNS fallback.

Mode-specific complete policies are:

- direct Runtime: Runtime Control/transfer, cluster DNS, and effective direct CIDRs;
- proxy-required Runtime: Runtime Control/transfer plus its own proxy Pod and proxy
  port only;
- no-network Runtime: Runtime Control/transfer only;
- proxy ingress: only the matching Runtime Pod on the proxy port; and
- proxy egress: cluster DNS plus effective inherited destination CIDRs. The addon is
  an additional domain/protocol check and cannot expand that NetworkPolicy boundary.

All policies select exact Provider/Runtime/role labels. The chart-owned default-deny
policy continues to select all Provider-managed execution-policy Pods. Provider
mode-specific policies are complete rather than additive fragments that preserve an
obsolete direct path.

## Desired, Applied, and Reconciliation Evidence

The database retains the existing one desired slot, optional applied slot, monotonic
configuration sequence, digest, desired generation, Provider acknowledgement, and
Runner acknowledgement. No network-resource table, CA table, policy-history table,
or persistent repair queue is added.

The resolved configuration contains a bounded `network_enforcement` section derived
from the effective Profile and exact Provider capability revision. It identifies the
effective mode, canonical policy digest inputs, mandatory Service mapping revision,
and immutable proxy artifact revision without containing Kubernetes names, Secret
values, private keys, or observed ClusterIPs. Observed ClusterIPs remain
Provider-native deployment evidence and are fenced through the Runtime Pod spec and
configuration digest used for application.

Kubernetes Provider protocol v3 replaces the v2 actionable kind `network_policy`
with one `network_enforcement` observation. Its `in_sync` result means the complete
mode-required bundle matches current Runtime and configuration evidence. A bounded
reason identifies the first repair class, while diagnostics expose only safe counts,
roles, and fingerprints. Runtime Control does not interpret individual Kubernetes
objects.

A current correlated `OBSERVE` completion with aggregate `drifted` evidence may
trigger one existing generation-, sequence-, digest-, and lifecycle-fenced
`UPDATE_CONFIGURATION`. The Provider then performs only operations valid without
Runtime recreation. If Runtime environment, mounted trust, DNS/hosts inputs, Pod
shape, PVC shape, or mandatory Service mapping differs, the Provider returns a
bounded `network_recreation_required` failure and reports the Runtime non-compliant
rather than acknowledging the configuration. Runtime status exposes required
recreation, while the older applied slot remains only prior physical evidence.

An explicit Runtime restart or existing scoped recreation operation advances desired
generation and configuration sequence while retaining the same current configuration
authority, then replaces the Runtime Pod and requires fresh Provider and Runner
acknowledgement. The Provider does not advance generation autonomously. Lost
observations, restarts, and narrow-repair dispatch failures retain the existing
later-periodic-`OBSERVE` retry boundary.

Provider acknowledgement is emitted only after the full required bundle is in sync.
The current Runner then adopts the same pending configuration evidence through the
existing ordinary heartbeat acknowledgement. Applied promotion still requires both
exact reports. Provider warnings, capability advertisement, or Pod existence alone
cannot promote applied state.

## Application Impact and Lifecycle

Application classification becomes mode- and input-aware:

| Change | Impact |
| --- | --- |
| Direct allowed/denied CIDRs only | `in_place` Runtime NetworkPolicy update |
| Proxy destination CIDRs only | `in_place` proxy egress NetworkPolicy update |
| Proxy domain policy only | `in_place` ConfigMap replacement and proxy Pod replacement |
| Proxy image or addon artifact only | `in_place` proxy Pod replacement |
| Network mode | `recreate` Runtime Pod |
| CA trust identity or trust-bundle content | `recreate` Runtime Pod and proxy as staged |
| Mandatory Service hostname or ClusterIP mapping | `recreate` Runtime Pod |
| Other Runtime Pod, Provider, Profile, scheduling, storage, or DinD input | Existing create/recreate rules |

A Provider capability revision change is not automatically a Runtime recreation. The
classifier compares the resolved material inputs: proxy-only artifact changes remain
in place, while any Runtime Pod, trust, hosts, or unrelated Provider contract change
remains recreation-required.

### Initial start and restart

For proxy-required start, the Provider ensures CA, policy ConfigMap, stable Service,
proxy policies, and proxy Pod readiness before creating or reusing the Runtime Pod.
Restart retains the CA, Service, Workspace PVC, and current policy identity while
replacing the required workloads. Runtime running state is not compliant until both
proxy and Runtime evidence match.

### Direct to proxy-required

1. Ensure and validate the logical-Runtime CA.
2. Create the current ConfigMap and stable proxy Service.
3. Create proxy policies and proxy Pod; wait for exact Ready evidence.
4. Replace the Runtime NetworkPolicy with proxy-only authority.
5. Delete and recreate the Runtime Pod with proxy environment, public trust, strict
   DNS, and current hosts mappings.
6. Accept Provider and Runner acknowledgements only for the new configuration.

The old Runtime may temporarily lose HTTP connectivity after step 4, but direct
customer egress is not retained while replacement proceeds.

### Proxy-required policy update

The Provider creates the new digest-named ConfigMap, removes the proxy Pod, creates a
replacement using the same CA Secret and Service, waits for exact readiness, and then
removes obsolete owned ConfigMaps. During replacement, external HTTP(S) may fail.
The Runtime never receives direct fallback and does not require recreation when its
proxy endpoint and trust remain unchanged.

### Proxy-required to no-network

1. Remove Runtime-to-proxy authority from the Runtime NetworkPolicy.
2. Recreate the Runtime Pod without proxy environment, public CA mount, or proxy
   hosts mapping.
3. Delete the proxy Pod, policy ConfigMaps, proxy Service, and proxy NetworkPolicies.
4. Retain the logical-Runtime CA Secret for future reuse.

### Stop, reset, and terminal deletion

Stop deletes the Runtime Pod, Runtime NetworkPolicy, proxy Pod, active policy
ConfigMaps, proxy Service, and proxy NetworkPolicies. It preserves only the Workspace
PVC and CA Secret among Runtime-specific durable resources. Reset preserves the CA
identity while applying the existing destructive PVC semantics; a running reset
recreates the required mode resources, while a stopped reset leaves no execution
Pod, proxy Service, ConfigMap, or active network policy. Terminal deletion removes
the complete owned set including PVC and CA Secret.

Transition and recovery operations never delete the Workspace PVC unless the
existing reset or terminal-delete command authorizes it.

## API and Product Projection

Admin infrastructure Profile APIs accept and return the v1/v2/v3 discriminated
union. Workspace Runtime Profile APIs accept and return Policy v1/v2. Selectable
Profile and compatibility projections include mode-specific missing capabilities.
Workspace Profile responses add a safe effective-network projection so the UI can
show inherited and effective mode, CIDRs, domain mode, and canonical patterns
without reproducing composition logic in TypeScript.

Runtime configuration state responses add bounded effective network fields for each
desired or applied slot:

- mode;
- domain mode where applicable;
- protocol summary;
- HTTPS inspection flag; and
- enforcement status derived from the existing overall configuration status.

They do not expose Kubernetes object names, ClusterIPs, CA certificates, private
keys, raw Provider diagnostics, or proxy logs. Runtime failure codes distinguish
unsupported Provider capability, policy expansion, mandatory Service failure, CA or
policy evidence mismatch, proxy readiness failure, network enforcement drift, and
recreation required.

Admin Provider detail displays operator attestation and structured warning-only
diagnostics from the active Provider connection, including checked-at and connection
generation; disconnected Providers show diagnostics unavailable. Infrastructure
Profile editing exposes explicit modes and mode-specific CIDR/domain inputs.
Workspace Profile editing exposes `Inherit`, permitted stricter modes, and only the
fields valid under the selected infrastructure authority. The server remains final
authority for hierarchy validation.

Workspace Profile list/detail and Runtime status surfaces use these product terms:

- `Direct network`;
- `Proxy required`;
- `No external network`.

Proxy-required guidance states that only external HTTP, HTTPS, and WebSocket are
supported, HTTPS is inspected, SSH Git URLs and arbitrary TCP/UDP do not work, and
certificate pinning or custom trust stores may fail. No-network guidance states that
required Azents Platform communication remains available and avoids describing the
Runtime as offline.

OpenAPI is regenerated after server model changes, followed by generated Python and
TypeScript Admin/Public clients. Both web applications update their typed form,
presentation, localized copy, and story/test fixtures from those generated models.

## Persistence, Migration, Rollout, and Rollback

Profile and Runtime configuration contracts require no PostgreSQL shape change:
infrastructure Profile `schema_version` and JSONB `spec`, Workspace Profile JSONB
`policy`, and Runtime desired/applied documents already store versioned canonical
contracts without database enums for schema versions or network modes.

One expand migration adds nullable safe operational-diagnostics JSONB and
`diagnostics_checked_at` fields to `runtime_provider_connections`. Existing rows
remain valid with no snapshot. The fields are connection-generation-scoped
observation only; they do not become Provider capability, Profile compatibility,
Runtime desired/applied state, audit history, or a correctness dependency. Rollback
may drop these nullable fields after removing the v3 diagnostics projection without
changing any network authority or Runtime configuration document.

Rollout is expand-first:

1. add server parsing, composition, compatibility, API unions, and generated clients;
2. add Provider protocol v3, typed Kubernetes resources, strict-mode workload image,
   CA/trust support, and Helm settings/RBAC;
3. deploy Runtime Control support before allowing a v3 Provider to connect;
4. keep strict attestations disabled until the operator has reviewed the deployment;
5. enable selected capabilities and create new v3/Policy-v2 Profiles explicitly;
6. retain all legacy stored and applied documents unchanged.

A new server rejects unknown Provider protocol or contract versions fail-closed. A
v3 Provider cannot register with a Control version that supports only Kubernetes v2.
During a rolling upgrade, Provider disconnect preserves durable desired/applied
identity but blocks lifecycle dispatch until a compatible connection returns.

Rollback disables strict attestations first, preventing new strict selections while
preserving stored Profiles and applied evidence. Existing strict Runtimes must be
stopped or moved through an explicitly compatible Provider version; they never
execute as direct through an older Provider. Legacy direct Profiles remain available
through their unchanged v1/v2 and Policy-v1 paths.

A later separately approved snapshot will migrate remaining legacy current data to
one latest contract and remove legacy creation, editing, parsing, and generated
surfaces. This Design does not perform that convergence.

## Failure, Retry, and Recovery

All Kubernetes mutations are idempotent and exact-name/ownership fenced. Already
matching resources are reused; asynchronous Pod deletion returns without applying an
immutable replacement until absence is observed on a later lifecycle retry.

Failures are classified as:

- incompatible or invalid configuration before Kubernetes mutation;
- warning-only deployment concern outside one Runtime application;
- retryable Kubernetes API or asynchronous deletion outcome;
- recreation required because Runtime Pod inputs differ;
- fail-closed Runtime application failure because required enforcement evidence is
  missing or mismatched; or
- terminal cleanup failure, retried through the existing lifecycle command boundary.

Provider recovery scans all owned resource roles, groups them by validated Runtime
ID, and reports bounded state from the Runtime Pod or preserved storage evidence.
Actionable aggregate observation occurs only for a current explicit `OBSERVE`
command carrying the canonical desired configuration. Watch and failover reports may
remain lifecycle-only and cannot claim aggregate enforcement in sync.

A stale proxy generation, stale ConfigMap, mismatched Service selector, changed
ClusterIP, missing Secret, broadened policy, or foreign label never satisfies current
readiness. Narrow repair updates policies or replaces the proxy. Runtime environment,
trust, DNS, or hosts drift requires explicit recreation. No recovery path generates
a new CA for an existing applied identity or widens to direct.

## Security and Permissions

The Runtime workload is untrusted. Proxy environment variables are compatibility
inputs, not the anti-bypass boundary. Complete Kubernetes NetworkPolicies and the
operator-owned enforcing CNI provide transport isolation.

The Provider ServiceAccount gains namespaced access to Services, ConfigMaps, and
Secrets in the dedicated workload namespace because the Provider already owns Pod
creation there. It also receives resource-name-scoped `get` access to configured
mandatory Platform Services in their namespaces. It does not receive cluster-wide
Service discovery, cluster-wide Secret access, TokenReview authority, node
credentials, host networking, or raw customer manifest input. Runtime Pods do not
receive the Provider ServiceAccount or an automatically mounted token.

The proxy runs as a dedicated non-root container with all Linux capabilities dropped,
no privilege escalation, RuntimeDefault seccomp, a read-only root filesystem where
supported by mitmproxy, read-only policy/CA mounts, bounded ephemeral storage, and no
Workspace PVC mount. The private CA never enters Runtime Control commands, Provider
reports, API responses, logs, or the Runtime container.

DinD retains its accepted privileged sidecar boundary. NetworkPolicy selects the
whole Runtime Pod, so Runner and DinD traffic share the same effective mode. Nested
containers receive no independent direct egress path through the Pod network.

## Observability and Operations

Structured Provider logs cover resource role, operation, Runtime ID, desired
generation, configuration sequence, result, retry class, and safe mismatch reason.
They exclude Secret data, CA PEM, proxy environment credentials, request bodies, and
raw policy documents.

Admin diagnostics expose attestation state, warning code, severity fixed to warning,
last check time, connection generation, and bounded safe detail. A disconnected
Provider exposes diagnostics unavailable. The snapshot is operational observation:
losing or clearing it changes only diagnostic visibility, never capability authority
or Runtime correctness. Runtime status uses the existing configuration
sequence/digest/generation projection plus effective network mode. Detailed
per-request proxy diagnostics remain only in ordinary proxy Pod logs.

Recommended operational alerts cover repeated proxy readiness failure, CA expiry
horizon, mandatory Service address changes, repeated aggregate enforcement drift,
Kubernetes API authorization failure, and strict-mode Runtime failure rate. Warning
checks must not be presented as data-plane proof.

## Requirement and ADR Traceability

| Requirement | Design mechanisms | ADR authority |
| --- | --- | --- |
| `REQ-1` hierarchy | Versioned v3/v2 contracts and server composition | `ADR-D1`, `ADR-D2` |
| `REQ-2` direct | Complete direct Runtime policy and legacy preservation | `ADR-D1`, `ADR-D8` |
| `REQ-3` proxy-required | Dedicated proxy, proxy-only Runtime policy, environment and trust | `ADR-D3`, `ADR-D5`, `ADR-D6` |
| `REQ-4` domains | Canonical exact/wildcard hierarchy and deny-final addon checks | `ADR-D2`, `ADR-D3` |
| `REQ-5` protocols | mitmdump/addon protocol boundary and no DNS/direct fallback | `ADR-D3`, `ADR-D5` |
| `REQ-6` HTTPS trust | Logical-Runtime CA, public-only Runtime trust, no passthrough | `ADR-D3`, `ADR-D4`, `ADR-D6` |
| `REQ-7` no-network | Platform-only Runtime policy and hosts mapping | `ADR-D5`, `ADR-D8` |
| `REQ-8` lifecycle | Provider-owned resource set and exact replacement boundaries | `ADR-D4`, `ADR-D6`, `ADR-D8` |
| `REQ-9` capability | Explicit attestations, warning-only checks, fail-closed application | `ADR-D7` |
| `REQ-10` applied state | Aggregate v3 evidence and existing desired/applied fences | `ADR-D6`, `ADR-D8` |
| `REQ-11` explanation | Safe API projections and Admin/customer UI guidance | `ADR-D1`, `ADR-D7`, `ADR-D8` |
| `REQ-12` logging | Redacted proxy stdout/stderr and existing cluster collection | `ADR-D3`, `ADR-D6` |

## Test Strategy

### E2E primary verification matrix

The focused E2E journey is deterministic and control-plane-only. It creates product
state through Admin/Public APIs and uses the real Runtime Control protocol with a
bounded fake Kubernetes Provider participant. It does not start a Kubernetes cluster,
create Kubernetes resources, execute packet probes, or claim data-plane enforcement.

| Scenario | Positive evidence | Negative evidence |
| --- | --- | --- |
| Legacy compatibility | Profile v1/v2 and Policy v1 remain readable with direct semantics | Strict fields are rejected from legacy contracts |
| v3 direct narrowing | API-created Workspace policy resolves to the inherited CIDR subset | Expansion is rejected before desired configuration |
| Proxy hierarchy | Unrestricted and allowlisted parent authority can be narrowed through Policy v2 | Denials cannot be removed and allowlists cannot be broadened |
| No-network hierarchy | A stricter Workspace override resolves to `no_network` | A Workspace cannot restore proxy or direct authority |
| Capability compatibility | An attested Kubernetes Provider accepts the supported strict contract | Docker or missing-capability Providers remain incompatible |
| Desired/applied projection | Current aggregate `network_enforcement` and Runner evidence promote the exact desired state | Stale, drifted, incomplete, or wrong-generation evidence cannot promote applied state |
| Tightening transition | Restrictive changes converge through the approved in-place or recreation classification | No API or protocol path reports a weaker fallback |

This E2E evidence proves API composition, compatibility, dispatch, fencing, and bounded
status projection only. Kubernetes resource construction and lifecycle behavior are
verified independently by Provider unit, manifest, protocol, and lifecycle tests.

### Deterministic coverage

Always-on tests cover:

- Profile v1/v2/v3 and Policy v1/v2 parsing, canonicalization, hierarchy, unknown
  fields, IDNA, wildcards, deny precedence, and invalid expansion;
- effective-Profile resolution from every supported legacy/new pairing;
- mode-aware required capabilities and Docker incompatibility;
- application-impact classification, including proxy-only in-place changes and
  Runtime trust/hosts recreation;
- Kubernetes resource manifests, exact ownership filters, resource comparison,
  lifecycle deletion matrix, stable Service handling, strict DNS/hostAliases, and
  Secret key exposure boundaries;
- CA generation, persistence, mismatch failure, public/private separation, and
  Runner trust-bundle bootstrap;
- addon policy vectors, redirect and authority checks, actual selected-IP checks,
  logging redaction, readiness evidence, and protocol denial;
- Provider v3 registration and aggregate `network_enforcement` report validation;
- Runtime Control fencing for current observe repair, stale report rejection,
  recreation-required outcomes, and exact applied promotion;
- Helm schema/render tests for disabled defaults, independent attestations, immutable
  images, mandatory Service references, RBAC, default deny, and absence of a DNS or
  proxy controller Deployment;
- OpenAPI/client regeneration, API projection tests, localized UI forms/status copy,
  and story/component tests.

A deterministic E2E lane may use a bounded fake Provider protocol participant to
verify the Admin/Profile/desired/applied journey without claiming Kubernetes resource
creation or packet enforcement. It must label its evidence as control-plane behavior
only.

### Testenv prerequisites and CI policy

Strict-network validation adds no Kubernetes prerequisite snapshot, live-cluster
workflow, packet-probe lane, or qualification artifact. Always-on CI runs deterministic
contract, Provider, proxy, Runner, Helm render, generated-client, and control-plane E2E
coverage without Kubernetes credentials or resource creation.

Warning-only deployment validation and test results are never capability authority.
Operator attestations remain the only capability-enablement input, while desired/applied
Runtime evidence remains the product truth for one concrete Runtime.

## Design Authority

- Design revision: `2`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Add Kubernetes Profile v3 and Workspace Policy v2 while retaining legacy direct documents unchanged | `network-260812/REQ-1`, `REQ-2`, `REQ-9`; `network-260812/ADR-D1` | `decided` |
| M2 | Resolve hierarchical mode, CIDR, and domain authority on the server before desired configuration | `network-260812/REQ-1`, `REQ-4`; `network-260812/ADR-D2` | `required` |
| M3 | Enforce complete direct, proxy-only, and Platform-only Runtime NetworkPolicies without mode fallback | `network-260812/REQ-2`, `REQ-3`, `REQ-5`, `REQ-7`; fixed constraints | `required` |
| M4 | Use one dedicated pinned mitmdump plus Azents-addon workload for each proxy-required Runtime | `network-260812/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-8`, `REQ-12`; `network-260812/ADR-D3` | `decided` |
| M5 | Persist one logical-Runtime CA, expose only its public certificate to Runtime, and fail closed on identity mismatch | `network-260812/REQ-6`, `REQ-8`, `REQ-10`; `network-260812/ADR-D4` | `decided` |
| M6 | Remove DNS from strict Runtimes and inject only observed mandatory Service host mappings | `network-260812/REQ-3`, `REQ-5`, `REQ-7`, `REQ-9`, `REQ-10`; `network-260812/ADR-D5` | `decided` |
| M7 | Keep Pod, PVC, policy, proxy, Service, ConfigMap, and Secret ownership in the Kubernetes Provider | `network-260812/REQ-8`, `REQ-9`, `REQ-10`; `network-260812/ADR-D6` | `decided` |
| M8 | Advertise strict capabilities only through independent operator attestations and store validation warnings as connection-generation-scoped operational diagnostics | `network-260812/REQ-9`, `REQ-11`; `network-260812/ADR-D7` | `decided` |
| M9 | Preserve existing desired/applied sequence, digest, generation, Provider, and Runner evidence as product truth | `network-260812/REQ-10`; current Runtime Provider and persistence Specs | `existing` |
| M10 | Add one protocol-v3 aggregate `network_enforcement` observation for v3 strict contracts, retain protocol-v2 `network_policy` for legacy direct contracts, and keep Control-fenced repair | M3, M7, M9; current Runtime Provider Spec requires a coordinated protocol revision for a new kind | `derived` |
| M11 | Apply CIDR changes in place, replace proxy-only resources for policy/artifact changes, recreate Runtime for mode/trust/hosts changes, and narrow first | `network-260812/REQ-8`, `REQ-10`; `network-260812/ADR-D8` | `decided` |
| M12 | Preserve Workspace PVC except at existing reset and terminal-delete boundaries | `network-260812/REQ-8`; current Agent Runtime Persistence Spec; `network-260812/ADR-D8` | `existing` |
| M13 | Project effective mode, limitations, compatibility, warnings, and bounded failures through Admin/Public APIs and web surfaces | `network-260812/REQ-9`, `REQ-11`; `network-260812/ADR-D7` | `required` |
| M14 | Emit redacted proxy diagnostics only through ordinary Pod logs | `network-260812/REQ-12`; `network-260812/ADR-D3`, `ADR-D6` | `decided` |
| M15 | Require deterministic API/control-plane E2E plus Kubernetes Provider/proxy unit, manifest, protocol, and lifecycle coverage without making tests capability authority | `network-260812/REQ-9`, `REQ-10`; `network-260812/ADR-D7` | `derived` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Kubernetes v1/v2 `network_policy` as the only new-configuration network shape | M1 | v3 `network_access`; legacy documents remain readable | Core contracts, resolver, APIs, generated clients, Provider parser | Schema and compatibility tests retain v1/v2 and require v3 for new strict contracts |
| Workspace Policy v1 as the only editable policy | M1 | Policy v2 for hierarchy; v1 remains direct-only | Public API, web form, generated clients | API/OpenAPI and UI tests cover both versions |
| Runtime DNS rule in strict modes | M6 | Strict DNS config plus mandatory `hostAliases` | Kubernetes Pod and Runtime NetworkPolicy builders | Exact manifest and comparison tests |
| Direct customer CIDR egress in proxy/no-network modes | M3 | Proxy-only or Platform-only complete Runtime policy | Runtime NetworkPolicy builder and comparison | Exact manifest equality and negative-rule assertions |
| `network_policy` as the only Kubernetes reconciliation contract | M10 | Protocol v3 aggregate `network_enforcement` for v3 strict contracts; protocol v2 `network_policy` remains legacy direct-only | Runtime-control library/protobuf, Provider, Control admission/reconciler | v2 compatibility tests, v3 aggregate contract tests, and no v2 strict-contract fallback |
| NetworkPolicy-only `UPDATE_CONFIGURATION` implementation | M11 | Mode-aware bounded enforcement-bundle update | Kubernetes Provider lifecycle | Impact and lifecycle tests prove proxy-only updates and recreation rejection |
| Kubernetes API boundary limited to Pod/PVC/NetworkPolicy | M7 | Typed Service/ConfigMap/Secret/hosts/DNS support | Provider API models and HTTP adapter | Model/manifest/HTTP tests and exact method grep |
| Provider RBAC limited to workload Pod/PVC/NetworkPolicy | M6, M7 | Narrow workload-resource permissions plus resource-name-scoped mandatory Platform Service reads | Helm RBAC | Render tests for exact namespaces, resource names, resources, and verbs |
| Runner without interception trust bootstrap | M5 | Public-CA validation and inherited child-process bundle | Runner startup and Provider Pod inputs | Runner tests, mount-key checks, and proxy trust/authority unit tests |
| CIDR-only Admin and Workspace Profile editors | M13 | Mode-aware CIDR/domain forms and explanations | Admin Web, Main Web, localization, stories | Component tests and Web Surface E2E |
| Runtime status without effective network mode | M13 | Bounded desired/applied network projection | Public API and Workspace Runtime panel | API and UI tests; no Kubernetes/private material fields |
| Provider connection projection without safe warning diagnostics | M8, M13 | Active-connection-generation diagnostic snapshot and disconnected-unavailable projection | Provider protocol, connection persistence, Admin API/UI | Migration, generation-fence, redaction, disconnect, and Admin projection tests |
| Strict-mode validation limited to API composition | M15 | Provider/proxy manifest, protocol, lifecycle, and authority tests alongside control-plane E2E | Provider/proxy packages and deterministic E2E | Focused unit suites plus API-created desired/applied journey; no packet claim |
| Existing MCP egress proxy | None | Retained independent server-side SSRF control | No change | Existing resource and tests remain |
| Workspace PVC lifecycle | None | Retained existing reset/terminal-delete authority | No change except proxy-resource coordination | Persistence regression tests |

## Feasibility

- **M1-M3 — feasible.** Current Profile and Policy documents are strict Pydantic
  models stored in JSONB with scalar schema versions. Adding discriminated versions
  does not require PostgreSQL DDL. The resolver already composes Workspace
  restrictions and computes canonical desired documents.
- **M4 — feasible with compatibility risk.** A new dedicated proxy image/addon is
  repository-local work. mitmproxy addon API and WebSocket behavior require pinned
  protocol and forwarding tests, but no architectural blocker was found.
- **M5 — feasible.** The Provider currently lacks a crypto dependency, while the
  repository already uses `cryptography`. Adding it to the isolated Provider package
  preserves the external Provider boundary. Kubernetes Secret item selection can
  expose only the public certificate to the Runtime. The Runner needs a new
  writable-bundle bootstrap path.
- **M6-M7 — feasible.** The Provider's typed Kubernetes boundary and HTTP adapter are
  intentionally small and can be extended. Current Helm RBAC lacks the required
  resources and must be expanded. The current chart supplies one stable
  `runtime-control` ClusterIP Service for Control and transfer; explicit configured
  Service references avoid relying on DNS parsing.
- **M8 — feasible with one expand migration.** The current durable Provider
  connection records authenticated generation and protocol but no diagnostics. Two
  nullable connection-observation fields plus a bounded Provider v3 diagnostics
  message support current/last-known Admin projection without changing the
  capability contract or creating qualification authority.
- **M9-M11 — feasible with a coordinated strict-contract protocol addition.** Runtime Control already
  fences desired/applied promotion and one-shot repair by Runtime, Provider
  generation, desired generation, sequence, and digest. The prior strict-contract
  shape had only Kubernetes v2 and one `network_policy` kind. Provider, shared
  library, protobuf, Control admission, tests, and Specs add the coordinated v3
  aggregate contract while retaining v2 for legacy direct operation.
- **M12 — feasible.** Current Provider lifecycle already separates PVC deletion from
  stop/restart/recreation. Proxy resources can follow their own retention matrix.
- **M13-M14 — feasible.** Existing API and UI surfaces already carry Profile,
  compatibility, desired/applied, Provider, and connection projections. They require
  bounded fields, the M8 connection diagnostics expansion, and generated-client
  updates rather than a new network-policy source of truth.
- **M15 — feasible.** Deterministic API/control-plane coverage runs in repository CI.
  Kubernetes resource semantics, ownership, comparison, replacement, cleanup, trust,
  authority, and selected-IP forwarding are covered by focused Provider/proxy unit,
  manifest, protocol, and lifecycle tests without requiring a live cluster.

No authority or implementation blocker remains. The main non-blocking risks are
mitmproxy addon compatibility, NetworkPolicy behavior differences across CNIs,
Service-IP handling differences around kube-proxy/eBPF, IPv6 coverage, CA expiry
operations before a rotation surface exists, and applications that ignore standard
proxy or trust variables. The Design addresses these through pinned artifacts,
operator attestation, warning-only diagnostics, fail-closed per-Runtime evidence,
deterministic focused tests, and explicit compatibility copy rather than fallback.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: 2026-08-12
- Approved Design revision: `2`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`, `M9`, `M10`, `M11`, `M12`, `M13`, `M14`, `M15`
- Approved scope: Hierarchical direct, proxy-required, and no-external-network authority; versioned Profile and Workspace policy contracts; Provider-owned Kubernetes proxy, CA, Service, ConfigMap, Secret, and NetworkPolicy resources; strict Runtime DNS removal and mandatory hosts mappings; operator-attested capabilities with warning-only diagnostics; desired/applied enforcement evidence; fail-closed replacement and recovery boundaries; Admin and Runtime projections; migration, rollout, rollback, deterministic API/control-plane E2E, and Kubernetes Provider/proxy unit, manifest, protocol, and lifecycle verification obligations.
