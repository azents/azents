---
name: scheduled-task
description: Create, explain, list, delete, or replace Scheduled Tasks for the current Azents Session. Use when a user asks an Agent to perform work once at a future time, repeat work on a schedule, manage existing scheduled work, or explain Scheduled Tasks in a Session or connected External Channel conversation.
---

# Scheduled Tasks

Create Scheduled Tasks from natural-language requests while preserving the current
Session and intended channel context.

## Core boundaries

- Always use the current AgentSession. Never create, select, or request another
  persistent AgentSession.
- Set `channel_id` to the same opaque channel handle that would be passed to
  `channel_action.binding`.
- Pass a channel handle unchanged. Never reconstruct provider, conversation,
  channel, thread, or resource identifiers.
- Set `channel_id` to `null` when the request does not target an External Channel
  conversation.
- Fail closed when the requested channel cannot be identified, is not connected,
  or is not authorized.
- Never silently fall back to the source channel, another channel, or a
  Session-only Task after a target failure.
- Use only the Scheduled Task tools exposed by the current runtime.
- Replace an existing Task through List → Delete → Add.
- Do not offer Pause, Resume, Rerun, or cancellation that preserves the Task.

## Operating modes

- Create a Task when the user explicitly requests future or recurring work.
- Explain the applicable creation behavior without calling a creation tool when
  the user only asks how Scheduled Tasks work.
- Use List and Delete for existing Task management.
- Replace a Task by deleting the existing definition and creating a new Task.

## Creation workflow

### 1. Resolve the channel target

Determine the target from the specific user message containing the Scheduled Task
request.

- For an External Channel request, default `channel_id` to the exact opaque
  channel handle associated with that message.
- For an ordinary Session request, default `channel_id` to `null`.
- If the user explicitly requests another connected channel, use that channel's
  handle instead of the source channel.
- When the Session contains multiple channel conversations, inspect the message
  origin and surrounding context carefully. Do not select a handle merely because
  it was used most recently.
- Preserve the exact conversation scope represented by the handle. Do not
  substitute a parent, child, nested, or adjacent conversation.
- If an explicitly requested target cannot be mapped reliably to exactly one
  available handle, ask one focused clarification or report that it is
  unavailable.
- Let the Scheduled Task tool perform authoritative connection and permission
  validation.

Read [creation-contexts.md](references/creation-contexts.md) for scenario-specific
behavior.

### 2. Interpret the schedule and timezone

#### Schedule field contract

Choose exactly one of these shapes:

- **One-time:** `at` is a timezone-bearing RFC 3339 timestamp, while `cron=null`
  and `timezone=null`.
- **Recurring:** `at=null`, while `cron` is a standard five-field expression and
  `timezone` is an IANA timezone identifier.

`at` and `timezone` are mutually exclusive. Never send a separate `timezone`
with `at`; the offset or `Z` inside `at` already defines the one-time instant.

```json
{"at":"2026-08-18T09:00:00+09:00","cron":null,"timezone":null}
```

```json
{"at":null,"cron":"0 9 * * 1-5","timezone":"Asia/Seoul"}
```

- For a duration-relative request such as "one hour from now," derive the instant
  from the current time without asking for a timezone.
- For a calendar-time request, use an explicitly stated timezone first.
- Otherwise, use a timezone that can be inferred reliably from the current user
  or conversation context.
- Ask the user to confirm the timezone only when the calendar time cannot be
  interpreted reliably without it.
- Do not repeatedly confirm a timezone already established by reliable context.

Read [schedule-interpretation.md](references/schedule-interpretation.md) for
canonical forms, validation, and examples.

### 3. Determine an actionable objective

Use the user's request and relevant Session context to determine:

- what work the Agent must perform;
- the context or scope needed to perform it;
- what constitutes completion; and
- what result the user expects.

Proceed without clarification when these are sufficiently clear. Ask only when
missing information would materially change execution or make the work impossible
to complete. Do not ask questions merely to improve wording.

Write a concise, self-contained objective that:

- includes relevant context needed during later execution;
- preserves the user's intent, constraints, and expected result;
- contains enough information to determine success or failure;
- does not copy the entire conversation;
- does not invent unavailable facts or authorization; and
- does not include system-owned trigger, continuation, or terminal-action
  instructions.

### 4. Derive a concise title

If the user did not provide a title, derive one from the objective.

- Use the user's language.
- Describe the scheduled work concisely.
- Do not repeat the entire schedule or objective.
- Treat the title as a display label, not a unique identifier.

### 5. Ask only necessary questions

Ask a focused clarification only when at least one material input remains
unresolved, such as:

- the work target or expected result is not actionable;
- calendar-time timezone cannot be inferred reliably;
- one-time versus recurring intent is unclear;
- the requested time or recurrence cannot be canonicalized; or
- the requested channel cannot be mapped reliably to an available handle.

Use existing Session context instead of asking the user to repeat known
information. Combine related missing information into one concise question when
practical.

### 6. Validate and create

Before calling the creation tool:

- ensure the objective is actionable;
- ensure the title is concise;
- verify the exact schedule shape: `at` with both recurrence fields null, or
  `cron` plus `timezone` with `at` null;
- reject any payload that combines `at` with `timezone`;
- ensure `channel_id` is either `null` or one unchanged channel handle;
- reject a new one-time schedule in the past; and
- do not submit a guessed channel target.

Call `add_scheduled_task` only after all materially necessary inputs are resolved.

### 7. Report the outcome

After successful creation, report:

- the created title;
- the interpreted schedule and timezone when applicable;
- whether the Task is Session-only or channel-bound; and
- any immediate registration-presentation outcome returned by the tool.

When creation fails, report the actual reason. Do not claim that a Task was
created, retry with another channel, or convert it to a Session-only Task unless
the user explicitly makes a new request.

## Existing Task requests

### List

Use `list_scheduled_tasks` and present returned Task definitions clearly. Do not
infer Task identity from title alone.

### Delete

Use the exact Task ID returned by the Scheduled Task tools. List first when the
user's intended Task is ambiguous. Never substitute a title, prefix, fuzzy match,
or stale identifier.

### Replace

1. List and identify the exact existing Task.
2. Preserve every user-defined field the user did not ask to change.
3. Resolve the replacement channel target using the creation rules.
4. Delete the existing Task by its exact ID.
5. Add the replacement as a new Task with a new ID.
6. Report both deletion and replacement outcomes accurately.

Do not describe replacement as an in-place update.
