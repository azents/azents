---
title: "Workspace Environment Variable Opt-In Requirements"
created: 2026-10-15
document_role: primary
document_type: requirements
snapshot_id: workspaceenv-261015
tags: [workspace, runtime, security, frontend]
---

# Workspace Environment Variable Opt-In Requirements

## Primary scenario

A Workspace manager registers common environment values once. An Agent administrator chooses individual keys for an Agent; that Agent's subsequent Runtime shell commands receive only the chosen shared values. Existing Agent-specific configuration remains independently usable.

## Problem and goals

Per-Agent values require repeated configuration across Agents. Sharing must reduce duplicate management without implicitly exposing every Workspace secret to every Agent.

## Requirements

### REQ-1. Shared configuration

Workspace Owners and Managers can add, edit, rename and remove shared variables. Members see only variable names and value-presence metadata. Values are encrypted at rest and never returned by ordinary reads or validation failures. Editing retains unchanged secrets without retrieving them.

### REQ-2. Explicit per-Agent opt-in

Workspace Owners and exact Agent administrators can choose each shared key independently from Agent settings → Runtime. Existing/new Agents and newly registered shared keys default to **unselected**. No automatic select-all mode exists. Public-Agent visibility and private-Agent access follow existing rules. Session pages do not expose the editor.

### REQ-3. Live bounded application

Chosen shared values apply to later shell commands without restarting Runtime. Existing processes retain their original environment. Agent-specific values take precedence on duplicate names; deselection removes only the shared contribution. Existing Toolkit contribution behavior remains otherwise unchanged.

### REQ-4. Safe deletion and identity

Deleting a shared key removes its selections. Recreating that name or renaming a key requires fresh Agent opt-in. A stale selection/edit of a deleted identity is rejected, not attached by matching name. Foreign-Workspace identities cannot be selected.

### REQ-5. Usable settings and evidence

Provide shared Workspace management and key-level Agent selection, draft Save/Discard, read-only/loading/error/empty states, override feedback and responsive localized UI. Verify the representative API-to-Runner flow with fake credentials and hash-only shell evidence; narrower tests cover authorization, identity, encryption and failure cases.

## Constraints and non-goals

No EnvVar Toolkit deprecation/removal/migration, Session overrides, Interactive Terminal/container-global injection, versions/history, runtime restart or operational deployment. Existing Agent-local limits remain unchanged; each shared source follows the same 50-key/64-byte-name/4096-byte-value/100-KiB bounds.

## Confirmation and delegated choices

The requester explicitly specified Workspace global configuration, key-level Agent choice, default none, and autonomous planning through PR on 2026-10-15. Those outcomes are fixed. Remaining bounded choices were delegated to the implementing Agent: Owner/Manager catalog writes, existing Agent management rights for selection, local-value precedence, and identity-reset on rename/recreation. These are identified as delegated choices rather than fabricated prior user research or separate approvals.
