---
title: "Confidential Browser Input Delivery Design"
created: 2026-10-16
implemented: 2026-10-16
tags: [browser, runtime, security, agent, testing]
document_role: primary
document_type: design
snapshot_id: sealedinput-261016
---

# Confidential Browser Input Delivery Design

- Snapshot: `sealedinput-261016`
- Requirements: [sealedinput-261016/REQ](../requirements/sealedinput-261016-browser-input.md)
- Decisions: [sealedinput-261016/ADR](../adr/sealedinput-261016-browser-input.md)
- Mode: Collaborative. Decision owner: requester.
- Scope: initial Browser field fill; implementation authorized as recorded under Design Approval.

## Result and bounded guarantee

An existing Agent Runtime environment entry is input to a release-provided Browser Skill script executing within the Agent's Runtime. The script reads the Runner public key from command environment, encrypts the selected environment value, and prints only an encoded ciphertext. The Agent sends that string in `browser_act.encrypted_text`. The Runner validates its existing Browser target and input permission, decrypts immediately before field fill, and returns the existing value-free action result.

Environment provisioning remains a delegation to the Agent to read and use values. This is a supported low-retention delivery path, not a mechanism to prevent an authorized Agent from inspecting its environment. It does not hide input from the receiving website or prevent arbitrary later scripts/site text from echoing it.

## Design Authority

- Design revision: `2`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | One key holder at Runner process composition root; private key only in memory and lost on process exit | ADR-D1; REQ-1, REQ-4 | decided |
| M2 | Inject current public key into each new Agent shell-command environment; helper reads public key and named source internally | ADR-D2; REQ-1, REQ-2, REQ-3 | decided |
| M3 | PyNaCl SealedBox encryption; bounded encoded ciphertext; no custom RSA/hybrid construction | ADR-D3; REQ-1, REQ-2 | decided |
| M4 | Explicit mutually exclusive `text`/`encrypted_text` for fill only, preserving ordinary text semantics | ADR-D4; REQ-1, REQ-4 | decided |
| M5 | Keep existing Browser capability, Session/Runtime generation, current target, observation and native input-conflict admission | session-browser Spec; REQ-1, REQ-4 | existing |
| M6 | Carry ciphertext unchanged through model/history/API/Control and decrypt only at Runner effect boundary; return value-free failures | REQ-1, REQ-2; ADR-D3, ADR-D4 | derived |
| M7 | Browser Skill guidance explaining authorized environment use, script import, Runtime execution, stdout collection and encrypted fill | REQ-3; ADR-D2, ADR-D5 | derived |
| M8 | No plaintext fallback or automatic input replay; re-encrypt explicitly after key loss without old-key recovery | ADR-D1, ADR-D3, ADR-D4; current Browser non-replay contract | derived |
| M9 | Release Skill script projected through current Run VFS, explicitly imported and executed with Runtime-owned dependencies | ADR-D5; [managed Browser Skill](../spec/flow/session-browser.md), [file import](../spec/flow/file-exchange-storage.md) | decided |

References such as ADR-D1 mean `sealedinput-261016/ADR-D1`; REQ-N means `sealedinput-261016/REQ-N`.

## Current behavior and gaps

- Agent-local and opted-in Workspace environment values are encrypted in server storage. Ordinary reads return names and value-presence, not values. Current prompt construction exposes names only.
- `make_exec_command_tool` reads the owning Agent environment immediately before command dispatch. Runner process-global environment and Interactive Terminal do not automatically receive these Agent settings. The helper must execute through the normal Agent command path.
- `BrowserActInput.text` becomes the shared `BrowserAction.text` and then `handle.fill(action.text)` in the Runner. No encrypted input alternative currently exists.
- Current Browser transport carries a closed command union. Action-field validation rejects unrelated input. Schema changes must cover the server tool model, shared contract/codec and Runner dispatch together.
- The current Runner reconnect loop recreates operation/browser managers. A key stored on one such manager would have connection-manager lifetime, contradicting the accepted process lifetime.
- The Browser Skill currently asks for human sign-in help when needed but does not teach encrypted delivery of delegated environment values.
- Managed Skill package resources include nested files in the immutable Run VFS projection. `import_file` verifies current Run ownership, projection membership, size and content hash before copying a projected file into Runtime. `load_skill` does not materialize these files.
- Current direct execution starts a Runner child process, so image files may be visible. The Runner application environment and Agent-managed Runtime tool environment remain distinct ownership boundaries.

## Architecture and ownership

```mermaid
sequenceDiagram
    participant V as Current Run Skill VFS
    participant A as Agent / model
    participant T as Existing file import
    participant R as Runner process key holder
    participant S as Runtime script subprocess
    participant B as Browser tool and Control
    participant W as Native website field
    A->>T: Import projected Browser Skill script
    T->>V: Resolve authorized immutable source
    T-->>A: Copied Runtime file path
    Note over A,S: Runtime-side dependency preparation uses ordinary tool provisioning
    R->>S: Current public key in command environment
    Note over S: Existing execution path also supplies delegated environment values
    A->>S: Execute imported script with environment variable name
    S->>S: Read value and encrypt using SealedBox
    S-->>A: Encoded ciphertext only
    A->>B: fill(ref, observation_id, encrypted_text)
    B->>R: Existing authorized Browser command; ciphertext unchanged
    R->>R: Current target/input checks, decode and decrypt
    R->>W: Native field fill with plaintext
    R-->>A: Existing action outcome or value-free error
```

### Distribution and execution ownership (M7, M9)

- The server release owns the Browser Skill source, including its encryption script. The current Run's immutable VFS projection is the source authority used by `import_file`; an older Run keeps its existing projected source.
- The copied script executes in the Agent's Runtime. Its Python dependency environment and cache follow ordinary Runtime user-space tool and storage rules. The copied file has the same Agent edit authority as other Runtime files; this feature is not a restriction against the delegated Agent.
- The Provider owns durable storage provisioning and mounts. Effective Agent Workspace paths continue to come from current Runner reports. Use the actual path returned by file import rather than deriving a Workspace location from server paths or Provider configuration.
- The Runner owns key management, command-time public-key injection and native Browser decryption. Its application package declares PyNaCl for that product responsibility. The Skill script separately declares its Runtime-side encryption dependency.
- Existing VFS and file transfer supply the distribution path; this feature adds no helper-install Runtime operation, Agent-facing Runner console entrypoint, global PATH change or encryption service.

### Key holder (M1)

Create a narrow process-owned object before entering the Runner reconnect loop. It owns a PyNaCl `PrivateKey` and exposes only a public-key encoding for command environment composition and a bounded decryption method for Browser fill. Do not serialize the holder or give it a repr containing private material.

Recreated Browser/operation managers receive that same holder. Their shutdown closes their own resources, not the process key holder. Transport reconnect does not rotate the key. Process exit loses it; the next process creates a new pair. No private-key file, server DB record, registration metadata or public API is added.

The Runtime identifier and existing accepted generation remain the routing authority. The public key is not a capability and does not authorize an input. Multiple Sessions in one Runner can use the same recipient key; normal Session/task/page checks still determine which target may be filled. This does not add a cross-Session secret-access rule beyond the current delegation model.

### Command environment (M2)

Use a Runner-owned slot named `AZENTS_BROWSER_INPUT_PUBLIC_KEY`. It contains the padded URL-safe Base64 encoding of the 32-byte public key (44 characters). The private key is never an environment entry.

For each new Agent `exec_command` process, compose the existing inherited and operation-provided environment as today, then set this public-key slot from the current process key holder. This slot is managed metadata, not an Agent credential source. Its Runner-generated value wins over a same-name caller/Agent setting so stale user data cannot silently redirect encryption. Existing precedence among all other Agent/Workspace/Toolkit values remains unchanged.

Do not copy the public key into a static startup-only subprocess environment. The per-command snapshot lets a future explicitly introduced key replacement affect new commands. A running process keeps its original environment. This snapshot does not add periodic rotation, a rotation timer, key history or an administrative API. It merely avoids making future key replacement require changing every tool caller.

Interactive Terminal and service processes retain current environment behavior. No plaintext Agent credential values are added to the Runner's global environment, registration or Control metadata.

### Helper and Skill (M2, M3, M7, M9)

Add `scripts/encrypt.py` beneath the release Browser Skill source. Its projected URI is `azents://skills/azents/browser/scripts/encrypt.py`. Import that resource with the existing `import_file` tool and use the exact returned file path. The default temporary import location is sufficient for one preparation sequence; re-import if the copied file is no longer present. A durable copy, if needed, uses an explicitly chosen path under the current reported Workspace and ordinary file-conflict behavior.

The script carries inline Python script dependency metadata for `PyNaCl==1.6.2` and a compatible Python requirement. Execute it using `uv run --no-project --script` so dependency resolution uses a Runtime-side script environment without discovering or modifying the current repository's Python project. The bundled Runtime currently supplies `uv`; if missing in another supported environment, follow existing Runtime user-space tool provisioning instructions. Unavailable tools, denied package access or failed resolution are prerequisite failures, not permission to change Runner packages or input plaintext. Package setup is ordinary Runtime dependency preparation and may emit package-status stderr; it never receives the confidential value as an argument.

Illustrative invocation, where the quoted script path must be replaced with the actual import result:

```console
uv run --no-project --script '<returned Runtime script path>' --env NAVER_PASSWORD
```

The script imports only Python standard library and PyNaCl APIs. It has no dependency on Runner modules or their interpreter. Source distribution is part of the existing release Skill packaging; Runtime caches/environments are ordinary user-space state, not persisted Browser key material.

The helper:
1. Accepts one validated environment variable name, not a plaintext value argument.
2. Reads `AZENTS_BROWSER_INPUT_PUBLIC_KEY` and the requested value using `os.environ` inside the command process.
3. Accepts an explicitly present empty value as empty text; an absent value is a value-free error.
4. UTF-8 encodes and limits the source to 4096 bytes, covering the current environment setting limit without a separate larger-payload protocol.
5. Uses `SealedBox(PublicKey(...)).encrypt(plaintext_bytes)`.
6. Prints exactly one padded URL-safe Base64 ciphertext line on success, without a JSON wrapper, ciphertext prefix, version, source value, debug output or key dump.
7. Returns nonzero on failure with a short fixed stderr reason. Do not include input values or underlying exception representations. Broken output pipes must not trigger a traceback containing local input state.

The existing Browser Skill must be updated in the same feature change, not left as a later optional documentation task. Agent-facing instructions explicitly explain that environment provisioning delegates reading and use, and teach the following tool sequence:

1. Obtain a current Browser target and field observation reference as today.
2. Call `import_file(uri="azents://skills/azents/browser/scripts/encrypt.py")`. Capture its returned absolute Runtime file path; a VFS URI is not itself a shell-executable path.
3. Ensure the Runtime command runner is available under existing provisioning policy, then call `exec_command` with the `uv run --no-project --script` invocation above using that path. The only credential selector is the environment variable name, not its value or a shell expansion. Inline dependency metadata supplies PyNaCl in the Runtime script environment.
4. If execution is still running, collect completion through existing `write_stdin` polling. Require exit code zero and exactly one bounded ciphertext line from stdout. Do not treat dependency-status stderr, helper stderr or incomplete process output as an encrypted value.
5. Copy that stdout line unchanged into `browser_act(action="fill", encrypted_text=...)` with current task/page/incarnation/ref/observation fields. The model does not encrypt or interpolate plaintext itself.
6. Repeat with the account-variable name for an account field when needed. If import, dependency preparation, public-key injection or source-variable access fails, report the value-free reason rather than echoing the source, requesting a password in chat or inventing a ciphertext.

The tool description links this workflow and identifies `encrypted_text` as script output. Release Skill resources, Browser tool contract and Runner support ship together; a documentation-only rollout advertising unsupported input is not a completed feature. Human CAPTCHA/MFA handling remains the current workflow; this feature does not solve those challenges.

### Cryptographic representation (M3)

Use PyNaCl SealedBox, which delegates ephemeral-key and ciphertext-integrity handling to libsodium. SealedBox is recipient encryption, not sender authentication. Existing Browser authority supplies execution admission.

The serialized tool value is just the ciphertext encoded as a bounded string. There is no algorithm negotiation, envelope version, timestamp, domain field, key registry, signature, one-use ledger or new capability token. No previous key is tried after decryption failure.

For 0..4096 plaintext bytes, SealedBox emits 48..4144 ciphertext bytes. Padded Base64 occupies 64..5528 characters. The helper and Runner validate these bounds. The tool schema uses a maximum of 5528 characters for `encrypted_text`; the shared wire decoder enforces the same maximum, and the Runner checks decoded bounds before attempting decryption. Require valid URL-safe padded Base64 and valid UTF-8 after decryption. Do not include encoded content in validation errors.

The encoding is not classified as a persisted versioned format. Its fixed construction is part of this one input contract; introducing a second construction later would require a separate decision rather than silent fallback.

## Browser tool and wire contract (M4, M5, M6)

Add nullable `encrypted_text` to the model-visible Browser action input and the shared BrowserAction DTO. Retain the existing `text` field unchanged.

Rules:
- For `action="fill"`, require exactly one non-null input: `text` or `encrypted_text`.
- An explicitly empty `text` remains ordinary empty fill.
- `encrypted_text` is forbidden for every other action in this snapshot.
- Both fields present, neither present, invalid encoding, oversized ciphertext or unsupported field combinations fail before native effects.
- No automatic detection in `text`. Text that looks like Base64 stays literal text.

Example, with synthetic ciphertext placeholder:

```json
{
  "task_id": "current-task",
  "page_id": "current-page",
  "resource_incarnation": "current-incarnation",
  "action": "fill",
  "ref": "current-password-ref",
  "observation_id": "current-observation",
  "encrypted_text": "<ciphertext output from helper>"
}
```

Keep the encrypted field unchanged through function-tool argument storage, event projection, Engine preparation, Runtime operation payload and shared Control codec. The server does not decrypt or replace the persisted arguments. Add the optional field to the closed wire shape in all encode/decode paths and tests. Populate it explicitly when constructing internal DTOs; existing literal construction sites pass null rather than introducing optional-constructor ambiguity.

No public REST/OpenAPI login endpoint or frontend field editor is introduced. Browser tool schema and shared Runtime DTOs are the affected contract surfaces. Public browser projection and human field-edit controls retain their current shape.

## Runner effect boundary and failures (M5, M6, M8)

Resolve the existing Session authority, current task/page/incarnation/frame and current observation reference exactly as ordinary fill does. Preserve interaction-guard admission, pending-dialog behavior and conflicting human input rejection. Only after this admission should the encrypted fill branch decode/decrypt.

Do not write plaintext back onto the shared BrowserAction, operation payload, event data or result. Pass the short-lived local decrypted string to the native fill call. Use the same native fill semantics and same action outcome, not a separate script-based DOM input path.

On an encrypted branch, handle expected decoding/decryption/native SDK failures at the narrow boundary and replace messages with value-free codes before generic diagnostics can log a native SDK call log. A Playwright timeout/error can include attempted fill values; return a fixed message instead of forwarding its string or exception chain. This change does not globally redact ordinary text action failures.

Suggested local error categories:
- `browser_encrypted_input_invalid`: malformed, corrupt or current-key-unreadable ciphertext/invalid UTF-8. No claim that the Runner can distinguish a changed key from arbitrary tampering without extra metadata.
- `browser_encrypted_input_failed`: admitted native fill failed. State may be uncertain; do not replay automatically.
- Existing stale-target, stale-observation, permission, dialog and input-conflict reasons remain unchanged where they happen before decryption.

If the process key changes, the old ciphertext is not recovered. The Agent may run the helper in a fresh command using the new public key, refresh current Browser refs where necessary, and explicitly decide the next input. Old target identities still fail under existing checks. A lost fill result does not authorize silent re-encryption/replay.

Treat plaintext as ephemeral Python/native-process data; deleting local references is best effort, not a secure-memory-erasure guarantee. The receiving page necessarily gets the value. Existing observation input-value filtering remains; this feature does not add a broad browser-wide taint tracker or log scrubber.

## Changes by layer

- Runner composition root: create and retain process key holder across recreated transport managers.
- Runner command dispatch/environment builder: inject current public-key snapshot on new Agent exec processes.
- Release Browser Skill script: environment-to-SealedBox preparation, inline Runtime dependency declaration, bounded output and fixed errors.
- Runner package: PyNaCl decryption dependency, independent of the script's Runtime dependency environment.
- Runner Browser manager: explicit encrypted fill branch, current-key decryption and value-free native errors.
- Runtime-control library: closed action DTO, codecs, allowed-field matrix and bounds; no private key dependency required in the shared DTO layer.
- Server Browser tool adapter/schema: pass ciphertext unchanged; add field documentation and preserve `hide_input_in_errors`.
- Browser Skill: supported delegated login workflow, VFS import, Runtime dependency execution, stdout collection and failure guidance.
- Tests/spec: Browser contract and Runtime environment specs updated only when implementation lands.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Fill validator that requires only `text` | REQ-1; ADR-D4 | Exclusive literal/encrypted fill input | Server tool model and shared action validator | Both/neither/other-action tests |
| Direct `handle.fill(action.text)` as the only fill branch | REQ-1; ADR-D4 | Ordinary branch retained; decrypt-at-effect branch added | Runner fill dispatch | Synthetic encrypted login succeeds without plaintext arguments |
| Current Skill lacks a supported delegated confidential fill path | REQ-3; ADR-D2, ADR-D5 | Add script import and Runtime execution workflow without removing human MFA/sign-in assistance | Release Browser Skill and nested script resource | Projection/import tests, guidance/schema tests and Engine E2E |
| Existing non-fill actions, plaintext history, profile state, environment delegation | REQ-3, REQ-4; current Specs | Retained; no deletion or migration | Unchanged product contracts | Regression and isolation tests |

No database state, old ciphertext format, configuration mode, generated public API client or key file is removed. There is no prior product encrypted-fill format requiring compatibility fallback.

## Migration, rollout, recovery and operations

No data migration or live profile transformation. Ship the release Skill/script, Runner decryption dependency, tool schema/DTO and Runner implementation together as one coherent feature change. Script dependencies resolve within Runtime under existing package/network policy. Old Runners do not support the new field; fail with a value-free unavailable/contract error instead of dropping the field, treating ciphertext as text or falling back to plaintext. The supported activation boundary is a new Run with the updated Skill projection and a compatible updated Runtime; exact-SHA E2E must use that Runner image. Do not add a persistent protocol-version registry or silent legacy fallback.

On an older Runner the public-key slot is unavailable and the closed Browser command codec rejects the unsupported field, even if the current Skill script can be imported. Retain those explicit unavailable/contract failures rather than adding a second feature-negotiation state or silently relaxing input. Do not advertise successful availability without the supporting Runner. Older Runs retain their projected Skill source and gain new resources only through the existing new-Run boundary; deploying the server does not mutate those projections.

Rollback removes the Skill/schema feature on new Runs and never decodes ciphertext as ordinary text. Existing Runtime script copies and package caches follow ordinary Agent file/tool ownership; rollback does not delete them or mutate retained Run projections. Ordinary Browser behavior remains available. No automatic deployment or Runtime restart follows from design approval.

Only value-free metadata belongs in observability: whether the encrypted branch was requested, stable outcome/reason, and existing operation/target identity under current diagnostic policy. Never record private key, environment value, decrypted text or SDK exception strings from confidential fill. Ciphertext may exist in ordinary tool history by design; copying it into generic metrics/logs is unnecessary.

## Test Strategy

### E2E primary verification

Use a credential-free synthetic account/password login fixture through the assembled Engine → Skill VFS import → Runtime dependency environment and script → Browser tool → Control → Runner path. Create unique canary environment values through the existing public Agent settings API. Use the normal Skill/import/script invocation and encrypted fill arguments. The synthetic site acknowledges the expected submitted input without returning the value to the model.

Required assembled-product cases:
1. Account and password values are delivered correctly, while tool-call/results and normal feature diagnostics contain no plaintext canary.
2. Runner process replacement invalidates old ciphertext and new command environment allows fresh encryption; no automatic native input replay.

No real account, third-party credential snapshot, CAPTCHA solver or network proxy is needed. Existing testenv Runtime fixture support is sufficient; add a focused synthetic login test in the existing web/public Browser family, reusing the assembled Engine/Runtime/native Browser boundary. A deterministic model fixture imports the real projected script, uses environment variable names and the script's actual ciphertext output, never places canary plaintext in a model request, and submits the resulting encrypted fill. Extend only the synthetic route and public Agent environment preparation needed for this flow. The required CI fixture must supply approved package access or a prepared Runtime-side uv cache for the script dependencies; the test still executes the declared script environment rather than the Runner interpreter. Record which prerequisite was supplied. Preserve existing ordinary-input and authority E2E coverage; exhaustive malformed-input combinations stay in narrow tests below. Do not test by directly writing production DB rows.

E2E evidence: exact source SHA, Runner image source selection, pytest/JUnit, normal diagnostic captures, canary absence assertions and synthetic server outcome. Log scanners must not print the canary when an assertion fails. Required CI failures cannot be reported as successful optional skips. Live external login checks remain optional, user-authorized and separate from synthetic acceptance.

### Narrow tests

- Key holder survives manager recreation/reconnect but a new holder rejects old ciphertext. No key bytes in repr/errors or command environment.
- Command public-key injection runs after regular environment composition; new processes get a coherent public/private pair. Existing processes keep snapshots.
- Release resource/projection test: the nested script is available under the Browser Skill URI in a new Run; older projections retain their prior membership. Existing import authorization/hash checks supply the Runtime copy.
- Runtime script smoke test under the ordinary unprivileged Agent user: import the projected script, execute the returned path with `uv run --no-project --script` from an unrelated directory, and verify `--help` without a key or source value. Verify dependency preparation in Runtime, ciphertext output with a command-injected public key, and value-free prerequisite failures. Use a Runtime Python environment with no import access to Runner application modules; execution must not activate the Runner virtual environment or change the user's default Python PATH.
- Helper covers missing variables/key, empty value, 4096-byte ASCII and multibyte UTF-8 bounds, oversized values and value-free stderr.
- Crypto round trip, randomized ciphertext, wrong-key/corrupt input, strict Base64/size/UTF-8 validation.
- Closed tool schema and shared DTO/codec tests for literal/encrypted mutual exclusion and other-action rejection.
- Native fill success, conflict/stale-ref before decrypt, partial/timeout SDK failure with a plaintext-bearing synthetic exception that must not escape.
- Literal action regression, tabs/profiles persistence, public projection/human field editing unchanged.

### Feasibility evidence already collected

An isolated PyNaCl 1.6.2 probe on the actual Python 3.14 Runtime successfully encrypted/decrypted empty, 16-byte ASCII, 4095-byte multibyte UTF-8 and 4096-byte values. Maximum ciphertext was 4144 bytes / 5528 encoded characters. Wrong keys and one-bit ciphertext modification were rejected. No real secret or product source modification was involved.

Pre-implementation repository inspection confirmed that the environment source reaches Agent command subprocesses, the fill DTO/codec and native effect are localizable, and the process composition root can hold a key outside the reconnect loop. Completed implementation verification is recorded below.

The VFS release loader recursively includes nested package files, `AzentsImportResolver` resolves the current Run's exact file membership, and the existing VFS transfer route checks ownership, size and hash. These existing contracts can distribute a Skill script without a new installation operation. The current Runner image supplies `uv`, but the script execution contract uses the Runtime's available command environment rather than an internal Runner package path.

A separate temporary inline-metadata script was executed with `uv run --no-project --script` from `/tmp`. It resolved PyNaCl 1.6.2 and passed a synthetic SealedBox round trip without a Runner application interpreter. That probe established dependency-runner feasibility; the actual product path was subsequently verified below. Offline package-policy denial remains an environment-specific prerequisite, not a completed live-policy test.

### Completed implementation verification

- Runner project: Ruff and type checks, full Pytest suite, `585 passed`. Coverage includes standalone script boundaries, empty/multibyte/maximum-size values, missing inputs, corrupt/wrong-key input, manager reuse, command-environment precedence, stale references before decryption, native encrypted fill and value-free native SDK failure.
- Runtime-control library: full Pytest suite, `485 passed`; focused Browser contract/wire checks cover exclusive literal/encrypted arguments and other-action rejection.
- Server Browser tools/Skill, Runtime Browser service and operation adapter: focused Pytest suite, `225 passed`, plus Ruff and type checks. Explicit encrypted failure reasons are retained without forwarding Runner exception content.
- Real assembled-product E2E: `test_confidential_environment_input_through_skill_and_native_browser`, `1 passed` with four existing fixture warnings. It provisions separate account/password values through public environment settings, loads the Skill, imports the real projected script, executes Runtime-side uv dependency environments and fills both native fields. The controlled site confirms a combined input hash without returning either value.
- The same journey calls the public restart operation on its isolated test Runtime, observes a higher desired generation, opens a fresh Browser target and rejects the old password ciphertext before the site receives input. New command environments prepare fresh ciphertext for both fields and the site verifies the new explicit input sequence. No automatic replay is introduced.
- Session history and Worker/Public/Control diagnostics are scanned for both plaintext canaries. A failed scan uses a value-free failure message.
- Existing Browser fixture parsing was corrected to distinguish assistant calls from tool results. Dedicated fixture tests cover returned paths, process polling/output, replacement-phase separation and required old-key rejection.
- Documentation catalog and staged whitespace checks pass. Exact-source CI is recorded on the implementation PR. No production deployment, live account test, operational Runtime restart or real-device Safari/IME acceptance is established by these synthetic checks.

## Authority and feasibility review

- REQ-1: M1–M6 and M9 provide the complete data path; feasible with additive Skill resource, command-environment, schema and Runner changes. First-use dependency resolution is conditional on existing Runtime tool/package access or a prepared cache.
- REQ-2: M6/M8 define normal output and native-error handling. Decryption occurs after serialized command/event handling; native-error tests verify fixed reasons, and assembled canary scans verify the real history/event and routine service-diagnostic pipeline.
- REQ-3: M2/M7/M9 preserve delegation, name-only prompt behavior and Runtime tool ownership; no broker/read-denial mechanism is introduced.
- REQ-4: M4/M5/M8 retain current native input and authority; regression/E2E required.
- All material choices trace to accepted ADR-D1..D5 or unchanged current Specs. Script/key names, the inline dependency-runner recipe, bounds from existing environment maximum and code organization are local implementation details within those approved ownership boundaries.
- No unapproved scheduled rotation, domain restriction, TTL, one-use state, content version, key history or read prohibition is present.

## Non-blocking risks and limits

- A model can still refuse or choose to expose a value using its existing authority; supported guidance cannot guarantee model behavior.
- The target page can read submitted input. Later page text/images can disclose it independently of this delivery path.
- General Runtime execution already carries broad authority; in-memory key placement is not isolation from a hostile same-process/privileged actor.
- Python and browser memory are not guaranteed to be securely erased.
- A running helper may finish with an old public-key snapshot during a future key replacement; decryption failure leads to explicit preparation in a fresh command.
- In-flight native fill outcomes may be uncertain even if the returned error omits values.
- First execution may need package downloads. Existing Runtime network/package policy is authoritative; denied dependency access leaves this workflow unavailable and does not justify weakening that policy.
- A temporary script copy can disappear and a retained Run can have older Skill resources. Re-import within the current projection or use the existing new-Run boundary; no automatic overwrite or projected-source mutation is introduced.

## Design Approval

- Mode: Collaborative.
- Decision owner: requester.
- Approved on: 2026-10-16 through the requester's explicit instruction to implement the corrected Design.
- Approved Design revision: `2`.
- Approved authority IDs: `M1, M2, M3, M4, M5, M6, M7, M8, M9`.
- Approved scope: Skill-delivered Runtime encryption script and dependencies, command-time public key, process-memory private key, explicit encrypted fill and existing Browser authority/non-replay boundaries.
- Implementation and verification are authorized. Merge, deployment, live credential use and Runtime restart remain outside this authorization.
