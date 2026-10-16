---
title: "Confidential Browser Input Delivery Decisions"
created: 2026-10-16
tags: [browser, runtime, security, agent]
document_role: primary
document_type: adr
snapshot_id: sealedinput-261016
---

# Confidential Browser Input Delivery Decisions

- Snapshot: `sealedinput-261016`
- Requirements: [sealedinput-261016/REQ](../requirements/sealedinput-261016-browser-input.md)
- Mode: Collaborative. The requester owns material choices.

## Confirmed direction and existing boundaries

The requester confirmed Browser field-fill scope on 2026-10-16. Agent environment provisioning delegates reading and use. Confidential delivery avoids routine plaintext tool arguments/history; it does not establish a barrier against the authorized Agent. The requester proposed a public-key encryption helper executing in the Runtime and private-key decryption at the Runtime Browser input boundary. No vault, broker, new environment-read restriction, website allowlist or approval ceremony is introduced.

Existing environment selection and command-time shell injection, Browser capability admission, concrete Session/Run ownership, Runtime generation fencing and exact target/observation checks remain authoritative.

## Material decision map

1. **Accepted — key ownership and lifetime (D1).** Runner-process memory; transport reconnect retains the key, process restart requires re-encryption.
2. **Accepted — public-key discovery (D2).** Public key in shell-command environment; helper reads it without a key file or separate discovery tool. D5 defines the helper distribution and execution ownership.
3. **Accepted — encryption construction (D3).** PyNaCl SealedBox; library-managed public-key encryption without a custom hybrid construction.
4. **Accepted — explicit Browser input contract (D4).** `encrypted_text` for fill, mutually exclusive with ordinary `text`; no magic prefix decoding.
5. **Accepted — Skill-delivered Runtime script (D5).** Release-bundled Browser Skill script, copied through existing VFS import and executed with Runtime-owned dependencies; Runner owns key management and Browser decryption.

## Decision log

### D1. Keep the key in the owning Runner process

- Accepted by the requester on 2026-10-16.
- Authority: sealedinput-261016/REQ-1, REQ-2, REQ-4.
- Decision: the owning Runner process holds the private key only in process memory. Its lifetime is independent of transport reconnects. A new process generates a new key; ciphertext prepared for a lost key is rejected without native input, and the Agent can obtain the new public key and prepare a new ciphertext.
- Rejected alternative: persisting the private key in the Runtime filesystem to keep old ciphertext usable across process restarts. The original environment source can be read and encrypted again, so durable key storage/cleanup is unnecessary for this workflow.
- Consequences: process restart invalidates outstanding ciphertext. No private-key file, backup, database, key history or implicit old-key fallback is introduced.
- Boundary: this is process-lifetime management, not an authorization restriction against the Agent or a promise to protect a process from an Agent with general Runtime code-execution capability.

### D2. Provide the public key in shell-command environment

- Accepted by the requester on 2026-10-16 through an explicit simplifying instruction.
- Authority: sealedinput-261016/REQ-1, REQ-2, REQ-3.
- Decision: keep the private key only in Runner memory and inject its public key into shell-command execution environment. A release-provided encryption helper, documented by the Browser Skill, reads that public key and the named source environment variable internally and prints only the ciphertext representation.
- Rejected alternatives: public-key files in the workspace, Browser observation metadata, and a new public-key lookup tool. They add an avoidable key-discovery/storage step to this workflow.
- Consequences: the public key follows the same owning Runner as the command executor. It is injected by the Runner's command-environment composition rather than sourced from Agent-configured values. No private material is placed in command environment, registration metadata or tool responses. Environment variable and helper command spelling are local Design details.
- Existing authority: command-time Agent environment injection and precedence remain unchanged except for the Runner-owned public-key slot. The existing command environment validation and browser target checks continue to apply.
- Feasibility note: the current reconnect loop recreates operation/browser managers inside one Runner process. The key owner must therefore be constructed at the process composition root and passed to recreated managers; it must not be owned only by a transport-generation manager.

### D3. Use PyNaCl SealedBox and keep the scope narrow

- Accepted by the requester on 2026-10-16, selecting the recommended simple construction and explicitly stating that unusually strict security is not required.
- Authority: sealedinput-261016/REQ-1, REQ-2, REQ-3, REQ-4.
- Decision: use PyNaCl's standard libsodium SealedBox API. The helper encrypts the UTF-8 environment value for the current Runner public key; the Runner uses its current in-memory private key to decrypt immediately before field input. Encode the ciphertext as a bounded string for tool delivery. Do not implement RSA/AES envelope assembly or a custom cryptographic primitive.
- Rejected alternative: RSA-OAEP plus AES-GCM hybrid envelope. Direct RSA encryption cannot cover existing maximum environment values, and the hybrid construction adds key/nonce/wrapper fields without a required benefit here.
- Scope: no signature system, TTL, domain binding, one-use token ledger, key history, scheduled rotation or persistent content-version scheme. Existing Browser authority and target/observation validation apply.
- Consequences: public-key encryption does not authenticate the sender and is not a new capability grant. Ciphertext can be deliberately reused while the current key exists; execution still requires existing tool authority. Corrupt or old-key ciphertext fails without native input. An explicit retry may encrypt again; neither encryption nor error handling automatically replays a Browser input.
- Feasibility evidence: PyNaCl 1.6.2 declares Python >=3.8 and publishes ABI3 wheels for Linux x86_64/aarch64, macOS universal2 and Windows; isolated round-trip/tamper/maximum-size feasibility checks remain part of Design validation.

### D4. Use an explicit encrypted fill argument

- Accepted by the requester on 2026-10-16.
- Authority: sealedinput-261016/REQ-1, REQ-2, REQ-4.
- Decision: add `encrypted_text` to Browser fill; accept exactly one of ordinary `text` and encrypted `encrypted_text`. Decrypt only the explicit encrypted branch at the Runner field-input boundary. Other browser actions retain their current allowed fields.
- Rejected alternative: detect and decrypt a magic prefix in ordinary `text`. That changes literal input semantics and makes ciphertext/plaintext ambiguity part of every input.
- Consequences: existing literal text stays literal. Invalid encoding, corrupt/obsolete ciphertext and invalid target fail without plaintext fallback. Existing dispatch outcome semantics and uncertain-action non-replay rules remain authoritative.
- Implementation details delegated to the Design: bounded Base64 string representation, helper/env spelling and value-free error codes. No new website restrictions, expiration or capability modes follow from this argument.

### D5. Deliver the encryption script through the Browser Skill

- Accepted by the requester on 2026-10-16 after reviewing Runtime versus Runner ownership.
- Authority: sealedinput-261016/REQ-1, REQ-2, REQ-3, REQ-4; existing managed Skill projection and file-import contracts.
- Decision: bundle the encryption script with the release Browser Skill. The Agent imports the current Run's projected script through `import_file`, then executes the returned Runtime file path using Runtime-side Python dependencies. The Skill teaches import, dependency preparation, environment-name-only invocation, stdout collection and encrypted fill as one complete workflow.
- Ownership: the server release and immutable Run projection own the distributed script source. The copied file, dependency environment and process execute within the Agent's Runtime authority. The Runner distribution owns its private-key holder, public-key injection and PyNaCl decryption dependency. The Agent-facing script does not import Runner packages or depend on the Runner's internal virtual environment.
- Rejected alternative: install a Runner-package console entrypoint and link it into `/usr/local/bin`. Current direct execution may share the image filesystem, but that does not establish Runner internals as the Agent tool distribution contract.
- Other alternatives: preinstalling the helper in each Agent Workspace adds provisioning and update ownership; a new encryption Runtime operation adds a separate product interface. Existing VFS-to-Runtime file transfer already supplies the required distribution boundary.
- Consequences: `load_skill` supplies guidance; `import_file` explicitly materializes the script. Source bytes follow current Run projection membership and hash verification, while the local copy follows ordinary Runtime file persistence. Initial dependency resolution may require permitted package access. Missing prerequisites fail without exposing environment values or falling back to plaintext.
- Clarification of D2: public-key environment delivery remains accepted. D2 did not authorize Runner-image packaging of an Agent CLI; this decision supplies that previously missing ownership contract.
- Local implementation details: script filename, Runtime dependency-runner invocation and package declaration may be chosen in the Design within these ownership boundaries. Dependency preparation contains no credential interpolation and does not alter the Runner application environment.
