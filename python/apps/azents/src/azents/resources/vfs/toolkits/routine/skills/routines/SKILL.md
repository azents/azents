---
name: routines
description: Create, inspect, edit, delete, and carry out Session Routines for ongoing objectives. Use for conditional checking where the model decides whether action or output is worthwhile, including requests with timing preferences, for managing existing Routines, or for completing an admitted occurrence. Use Scheduled Tasks when output is required at every scheduled occurrence.
---

# Session Routines

Keep each Routine in the current root Session and use only its exposed Routine
tools. Explain behavior without creating a definition when the user only asks how
Routines work. Existing action permissions still apply to every investigation,
external write, and disclosure.

## Choose Routine or Scheduled Task

Choose by the output obligation, not merely a requested time or interval:

- "Produce a traffic-analysis report every hour" requires output each time: use
  a Scheduled Task.
- "Check traffic every hour and tell me if anything is unusual" requires
  conditional checking: use a Routine. A timing preference does not turn this
  into a mandatory-output Scheduled Task.
- A one-off investigation does not automatically create a Routine.

Explain the supported timing limits: source checking uses fixed 30-minute ticks,
and the Session-wide 30-minute minimum action interval determines eligibility,
not an exact execution time. Ordinary Session work can delay judgment at its FIFO boundary.
Do not promise arbitrary per-Routine schedules or exact hourly execution.

## Manage definitions

- Use `create_routine` with the user's intended title, objective, and supported
  sources. Preserve exact content; do not silently trim, rewrite, or truncate it.
- New definitions use a readable title-derived slug, without a UUID or automatic
  collision suffix. A duplicate slug in the same Session is rejected rather than
  replaced. Read the inventory and distinguish the intended objective before
  creating another definition; title edits preserve the existing slug.
- Use `sources=[{"type":"manual"}]` for the supported regular-check candidate
  source. Here `manual` is a source type, not a Run button or a requirement for a
  human to trigger each check. An empty source list makes no automatic candidate.
- Explain that checks use normal eligible ticks, not immediate execution on
  creation or an exact-time guarantee. Do not offer a manual Run, Pause, Resume,
  destination selector, priority, or unsupported source.
- Use `list_routines` to identify an existing definition and `inspect_routine` to
  read its exact current content and bounded recent work records. Preserve the
  returned slug rather than guessing one.
- Before `update_routine`, read the complete current content. Pass it unchanged
  as `expected` and put intended edits separately in `changes`. Omit unchanged
  fields; do not use null to mean omission. On a content conflict, reread and
  reconcile the user's requested edit instead of overwriting another change.
- Use `delete_routine` to remove future selection and retained definition records.
  Already-admitted work can still finish from its original context. Do not
  promise that definition deletion cancels an active ordinary Run.
- Respect the Session limit of 20 definitions and the retained latest 100 work
  records per Routine. Do not substitute another Session to evade a limit.

## Carry out admitted work

1. Use the immutable admitted objective, source context, previous result, and
   next-check hint. Do not replace that objective with a newly edited definition.
2. Keep ordinary Session work, other Routine occurrences, and Channel Work
   independent. Use `read_routine_context` with the exact slug and execution ID
   when a continuation gives only an identity reference for another occurrence.
3. Investigate within existing permissions. If the objective cannot reasonably
   be achieved, record an honest failed objective and useful future hint. Do not
   claim success because a command was attempted or a prerequisite was missing.
4. Call `record_routine_result` separately for each completed occurrence. Supply
   top-level `objective_outcome` (`finished` or `failed`), concise `result`,
   required `next_hint`, `notify`, `message`, and `files`. Do not nest under `work`.
5. Let ordinary incomplete-work continuation carry remaining occurrences. Do not
   create another persistent Session, timer, judgment loop, or duplicate Routine
   to keep an admitted occurrence running.

## Choose notification independently

- Prefer `notify=false` when nothing requires the user's attention, and set
  `message=null` and `files=null`. Routine execution does not imply a notification.
- Use `notify=true` only when the user needs to know, with a nonblank `message`.
  Keep objective outcome, saved result, future hint, and notification distinct.
- Attach files in the same result call using `files` with absolute Runtime paths
  or authorized `exchange://` URIs; use null when there are no files. File
  preparation failure leaves the occurrence incomplete. Files follow the same
  current Primary or Session chat destination as the message.
- Let the result tool use the current Session Primary at delivery time, or Session
  chat only when no Primary exists. Do not supply or reconstruct a destination.
- Do not use `channel_action.finish` or a Scheduled Task terminal tool to complete
  Routine work. A Routine result settles one occurrence, not its host Run or an
  unrelated participant Work cycle.
- Read the actual saved and delivery outcomes. A failed or unobserved publication
  does not undo completed work and is not proof of delivered notification. Do not
  resend automatically, settle a second result, or switch to another destination.

## Respect lifecycle boundaries

Treat explicit Stop as cancellation of current attempts, not deletion or pausing
of future definitions. Preserve original context across ordinary owner handover
and authorized retry. After archive, finish only the already-preserved work; do
not recreate removed definitions or source checks. Restore does not recreate
Routines or automatically resume future checking. Do not bypass purge or stale
owner rejection to force completion.
