---
title: "Safe Runtime Operation Admission Decisions"
created: 2026-10-26
tags: [runtime, reliability, backend]
document_role: primary
document_type: adr
snapshot_id: runtime-261026
---

# Safe Runtime Operation Admission Decisions

Authority: [runtime-261026/REQ](../requirements/runtime-261026-safe-operation-admission.md).
Mode: Autonomous. The requester approved the requirements and delegated the remaining bounded technical decisions. The dedicated technical interviewee is the decision owner.

## Decision map

- D1 accepted: atomic ordinary automatic-start handoff and concurrent join.
- D2 accepted: explicit immutable preadmission authority and typed no-append retry boundary.
- D3 accepted: existing finite phases, cancellation, and distinct unsubmitted outcomes.
- Fixed: no Session working-folder changes; no replay after acceptance or ambiguous submission; retain valid applied configuration authority; no production deployment or merge.
- Local details: names, helper decomposition, deterministic fixture composition.

## D1. Prove the exact ordinary automatic-start transition

**Question:** How can an original operation follow its normal automatic start, including concurrent callers, without following an unrelated lifecycle/configuration replacement?

**Decision:** Use an atomic automatic-start-or-join transaction with bounded current predecessor evidence. Store a nullable predecessor sequence/generation pair on current Runtime authority. The current sequence, desired generation, digest, and Runtime identity provide the successor. Match the exact stopped predecessor before advancing lifecycle/configuration once, or join only the exact immediate current automatic-start successor. Return the committed authority, not an unconstrained later read. Capability fencing remains mandatory.

All nonautomatic lifecycle and material configuration mutations invalidate this receipt in the same transaction. Connection replacement and ordinary observations/acknowledgements do not invalidate it. The receipt cannot authorize a chain of transitions and is not a history or operation log.

**Rejected alternatives:**

- Start before every model invocation: unnecessary compute and latency for conversations that do not use Runtime tools.
- Replace expected authority with the latest read: silently follows unrelated changes.
- Infer normal start from adjacent counters and current START command: restart completion can rewrite RESTART to START, so it does not prove origin.
- Fail every losing CAS caller: safe but does not satisfy the approved concurrent first-use outcome.
- Process-local or Redis-only serialization: not a cross-worker correctness authority.

**Consequences and risks:** Add a bounded nullable schema extension and inventory every lifecycle/configuration mutation for invalidation. Preserve existing Provider/Runner acknowledgement qualification and retained applied authority. Test restart handoff, explicit start/stop, profile ABA, recreation, capability removal, and concurrent ordinary callers. Missing invalidation is a correctness defect.

**Authority:** REQ-1, REQ-2. Accepted by the dedicated technical interviewee on 2026-10-26.

## D2. Carry explicit authority to the atomic admission boundary

**Decision:** Carry an immutable request-local authority token from the original qualified Runtime operation target through eligible standalone bash, process-start, and ordinary file operation APIs. It freezes Runtime identity, capability version, physical desired generation, selected applied sequence/digest, and Runner-reported Workspace. Revalidate before admission. Only the connection generation may be refreshed while every frozen authority remains valid.

Repeat admission only after typed route-unavailable or stale-generation rejections that prove no request was appended. An accepted dispatch ends retries permanently; an arbitrary exception is ambiguous and propagates. Unbound callers retain exact-generation behavior. Browser/configuration, process-handle/input/observation, Terminal, and generation-bound transfer operations are excluded from generic rebinding.

Staged file-write/patch bodies are immutable and staged once before admission. Reuse that exact body through proven no-append rejections; do not restage or replay it. Return the actual accepted connection generation in internal dispatch results and use it for reply observation and cancellation.

**Rejected alternatives:** scalar-generation-based inference loses original authority when reconnect already occurred; hidden context variables or a mutable client risk cross-request authority leakage; retrying a whole tool can duplicate effects; cross-generation replay violates REQ-3.

**Authority:** REQ-2, REQ-3. Accepted by the dedicated technical interviewee on 2026-10-26.

## D3. Bound admission by existing deadlines

**Decision:** Preserve the existing maximum 120-second target-resolution phase. All body staging, preadmission checks, reconnect waits, and submission attempts share each operation's existing fixed deadline; neither phase resets per retry. Check expiration and task cancellation before every submission and honor the existing bash cancellation callback during admission. Poll no slower than the existing one-second pattern without creating a new user setting.

Use internal `runner_admission_timeout` for a deadline exhausted before submission is known to have occurred, and `runtime_authority_changed` for a rejected frozen authority. Unexpected transport exceptions remain ambiguous and are never converted to a retryable non-submission claim.

**Rejected alternatives:** unlimited waits, a fresh deadline on each reconnect, arbitrary exception retries, and new configuration knobs expand recovery semantics or can submit work after cancellation/expiry.

**Authority:** REQ-3, REQ-4. Accepted by the dedicated technical interviewee on 2026-10-26.
