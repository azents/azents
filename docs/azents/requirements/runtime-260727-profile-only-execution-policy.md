---
title: "Profile-Only Runtime Execution Policy Requirements"
created: 2026-07-27
updated: 2026-07-27
tags: [runtime, policy, profile, admin]
document_role: primary
document_type: requirements
snapshot_id: runtime-260727
implemented: 2026-07-27
---

# Profile-Only Runtime Execution Policy Requirements

- Snapshot: `runtime-260727`
- Document reference: `runtime-260727/REQ`

## Problem

The installation-wide Platform ceiling duplicates the complete policy already stored by each
Profile. A saved Platform value can therefore appear enabled while the selected Profile silently
reduces it, and the reserved Standard Profile cannot correct the result because its policy is
read-only.

## Requirements

### REQ-1. Profile is the complete ceiling

Each Profile stores the complete Runtime execution authority ceiling. Resolution starts from the
selected Profile, then applies only restrictive Workspace and Agent contributions.

### REQ-2. No Platform execution policy

Remove the Platform policy API, Admin surface, persistence resource, audit vocabulary, source
version, and Runtime snapshot evidence. No backward-compatible Platform policy contract remains.

### REQ-3. Editable Standard policy

The reserved `system-standard` identity cannot be retired, but its metadata and complete policy are
editable with the same expected-version and Provider-capability validation as other Profiles.

### REQ-4. Direction-sensitive application

A restrictive edit to the selected Profile may converge automatically. Profile authority expansion
remains pending until explicit Agent Apply. Changing the Agent's selected Profile or override also
requires explicit Apply.

## Confirmation

Confirmed by the requester on 2026-07-27, including removal without backward compatibility.
