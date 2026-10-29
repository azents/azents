# Agent inference Proxy

An independent package of the original LiteLLM Proxy plus Azents custom auth,
request hooks and a closed Agent ingress. It is not the Worker inference loop or
a second canonical provider backend. Its approved authority is
[`relay-261028` Design revision 1](../../../docs/azents/design/relay-261028-model-inference.md).

## Current acceptance boundary

The server performs online admission for each call. Vertex's credential-keyed
SDK token cache does not grant Agent authority. Bedrock role configurations use
server-prepared STS sessions rather than Proxy-side ambient role resolution;
direct static-key configurations use their explicit keys. Request-private
extension bindings are released at cleanup; SDK cache memory is not claimed to
be securely erased. Deterministic integration and packaging acceptance is tracked
separately from live-provider entitlement.

No real provider account, subscription entitlement or billable inference is
verified here. The existing Worker remains unchanged. The representative assembled
journey uses real public/Admin APIs, authority over verified TLS and the built
Proxy, controlling only final provider networking. Deployment and live-provider
acceptance require separate operational authorization and eligible accounts.

## Composition and startup

- Published LiteLLM wheel: `1.109.0.dev1`, with registry artifacts hashed in `uv.lock`.
  The requester approved this one-time dev-release exception on 2026-10-29 for
  ChatGPT request-credential forwarding (upstream PR #41522). Replace it with the
  first stable containing that fix after equivalent auth/isolation/stream checks.
- Original Proxy application/config loader and lifespan, no model deployment
  registry, no Router dispatch or credential DB.
- The `proxy` extra is deliberately not installed: its Enterprise dependency is
  outside this artifact. `audit.py` checks installed files, premium configuration,
  original MIT notice and exact published-release identity. It never changes license gates.
- The image installs the published wheel with `uv.lock` and explicitly disables
  LiteLLM source builds. Only the installed environment enters the nonroot final
  stage; no upstream checkout, Rust toolchain or Enterprise tree is included.
- `NOTICE.md`, original distribution notices and the generated installed inventory
  are retained. Dependencies keep their own licenses.

Required environment:

```text
AZ_LLM_PROXY_AUTHORITY_URL=https://private-authority.example/internal/llm
AZ_LLM_PROXY_RESOLVER_KEY=<resolver-only service credential>
```

Optional deployment-only settings are `AZ_LLM_PROXY_AUTHORITY_CA_FILE`,
`AZ_LLM_PROXY_AUTHORITY_TIMEOUT_SECONDS` (15), and `AZ_LLM_PROXY_PORT` (4000).
The CA file extends the private authority channel's trust configuration, never
turns verification off. System trust roots apply when absent. No server-wide
`envFrom`, issuer token, provider-key environment or exporter is accepted.
The upstream boot guard receives a fresh undisclosed process-local nonce; that
nonce is not issued to clients and cannot bypass online Agent authentication.

## Public calls

Only `POST /v1/responses` and `GET /v1/models` accept an Agent bearer. Responses
must supply the actual configured model and `metadata.azents_target_id` computed
by `azents_llm_contract.target`. Listing is not an invocation prerequisite.
Authentication resolves the selected candidate online; only identity/target
selectors, never content, cross the authority channel. The returned credential is
private to the request, not a globally selected account. Health probing is the
original Proxy's credential-free `/health/liveliness` route; it does not establish
provider entitlement or authority reachability.

The decoder closes SDK protocol objects, admits bounded inline history/media,
and rejects remote/stored media, provider resource references, background/store
operations and SDK/config/header/account overrides. Request content is bounded
to 32 MiB. Caller function argument schemas remain opaque user data, not an SDK
configuration surface.

## Settings mapping

Current Agent settings remain the sole preference and capability authority.
`ModelConfiguration.protocol` comes from the server's existing route projection;
the Proxy does not infer that fact from model names.

| Control | Normalization boundary | Verification layer |
| --- | --- | --- |
| temperature, top-p, top-k, stop | Saved non-null defaults apply on omission; explicit request values remain subject to current support facts | units plus native/Anthropic/Gemini sampling/stop wires |
| output cap | Saved candidate cap is authoritative; smaller caller cap wins; known hard maximum clamps; unknown maximum invents no cap | units and Anthropic wire |
| reasoning | Saved default only on genuine omission; explicit clear stays clear; effort/summary and conditional tool coexistence checked | omission/clear/conditional units; Anthropic adaptive effort and Gemini thinking-level wires; explicit native encrypted continuation/history |
| structured text / strict tools | Exact closed Responses declarations, current feature constraints, LiteLLM owns provider conversion | decoder/settings units; native OpenAI strict/schema wire; exact Anthropic output format and Gemini JSON schema/MIME wires |
| function tools | Caller declarations stay client-executed; Proxy never runs them | unit and native/Anthropic/Google wire coexistence |
| hosted search | Saved selection compiles into provider-native search; restricting settings must survive or fail preparation | native OpenAI/xAI, Anthropic and Gemini controlled wire |
| hosted images | Google selection compiles modalities and image controls; API-key/OpenAI/subscription image tools remain client-executed | unit ownership matrix and Gemini PNG/usage wire |
| cache / execution option | Public cache controls admitted; finite ChatGPT supported `extra_body` correction preserves cache key/ultrafast; Fast normalizes to priority only when supported | normalization units and native ChatGPT stream/nonstream wire |
| generated image history | Native history stays native; generic bridge receives existing Worker-style provenance and exact inline bytes | history units and Anthropic wire |

Provider compatibility corrections are finite hook-built values, not caller
passthrough, provider-class monkeypatches or a maintained upstream fork.

## HTTP ownership, lifetime and errors

LiteLLM owns provider mapping, signing, HTTP protocol, response conversion,
streaming and usage. The extension supplies an official client at the deployment
hook and checks the actual transformed destination against the admitted route.
The standard HTTPX handler has redirects disabled. A supported transport wrapper
reclassifies retry-triggering connection errors to prevent the pinned handler's
hard-coded resend; it does not reconstruct, parse, buffer or replay requests.
The standard OpenAI SDK/HTTPX2 client is used for Kimi with `max_retries=0` and
request-lifetime cleanup. Cookies and environment proxy inheritance are disabled.
Stream failures/cancellation close the owned transport; native Responses failures
use LiteLLM's `response.failed` event rather than a false completion.

Provider error bodies, headers, arbitrary messages/extra fields and exception
traceback values do not become client or vendor-log output. Public errors retain
safe status/type and authority-versus-provider parameter classification when the
standard error envelope has that field. Native Responses stream failures retain
the attempted response/model identity and safe error code in their normal schema.
Vendor diagnostics retain origin/severity/exception class, not arbitrary payloads.
The original Proxy's typed response/deployment callbacks and outer ASGI lifetime
project one allowlisted JSON
operation event with a fresh correlation ID, verified Agent/Workspace/integration,
model, actual terminal/delivery outcome, monotonic latency and available token counts.
Accounting success contributes usage, not proof of completion. Disconnected,
cancelled and incomplete calls remain distinct from delivered success; preparation
rejection remains distinct from physical provider failure. Missing usage remains
null; token counts are not a subscription invoice. No ledger or external exporter
is installed.

## Local validation

From this directory:

```console
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check --error-on-warning
uv run pytest -q
uv run python -m azents_llm_proxy.audit
uv build --wheel
```

The test plugin forbids unmocked sockets, Requests and HTTPX2 fallbacks. Real Proxy
config/ASGI and provider serializers run against controlled transports; tests do
not authorize real accounts. Runtime LiteLLM is installed from a published wheel;
no upstream source compiler or Git checkout is required.
From the repository root, build with:

```console
docker build -f python/apps/azents-llm-proxy/Dockerfile -t azents-llm-proxy:local .
```

The independent, default-off chart profile and required resolver/CA Secret inputs
are described in `infra/charts/azents/README.md`. CI runs package checks and image
composition smoke tests; image success and all-provider acceptance are distinct.
