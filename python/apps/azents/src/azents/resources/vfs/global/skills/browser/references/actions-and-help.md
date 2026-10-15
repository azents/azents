# Actions and Human Help

Use the current task/page/incarnation from a result. For an element action,
replace `REF` and `OBSERVATION` with the chosen entry's current `id` and
`observation_id`, and retain its frame scope.

## Structured actions

```json
{"tool":"browser_act","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","action":"click","ref":"REF","observation_id":"OBSERVATION"}}
```

Fill a current control, then observe the page before the next dependent action:

```json
{"tool":"browser_act","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","action":"fill","ref":"REF","observation_id":"OBSERVATION","text":"Example search"}}
```

Use the supported structured select/check/press/scroll/hover/drag actions as
appropriate. Keep argument combinations aligned with the discovered tool schema.
Actions do not accept an arbitrary browser script.

Navigation uses the existing page or explicit frame target:

```json
{"tool":"browser_act","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","action":"navigate","url":"https://example.test/orders"}}
```

`back`, `forward`, `reload`, page closure and page dialogs require the main page.
Use a fresh observation after navigation rather than reusing prior references.

## Pre-arm events and answer dialogs

When a current control is expected to open a popup or download, register that
expectation on the triggering action:

```json
{"tool":"browser_act","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","action":"click","ref":"REF","observation_id":"OBSERVATION","expect":"popup"}}
```

Inspect the returned `popup` or `download`. A dialog may suspend the original
operation with `action_state="dialog_pending"`; this does not mean the trigger
should be sent again. Answer the exact current dialog:

```json
{"tool":"browser_act","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","action":"dialog","dialog_id":"DIALOG","accept":true}}
```

Supply `text` only for the intended prompt response. Consecutive dialogs have
distinct identities; inspect the next result. Dismissing or accepting a dialog
does not by itself prove a site workflow completed.

## Sign-in, conflicts and uncertain outcomes

Explain the required human step and identify the current task/page in the
Session Browser panel. For example: ask the user to sign in on that page and
tell you when finished. Do not ask them to copy a password, cookie or one-time
code into the conversation.

After human interaction, observe again and use the new references. If another
actor is in a gesture, key sequence or composition, an input-conflict response
means that actual interaction must finish first. Passive viewing does not
reserve the task; continue independent work where useful.

Read-only access permits observation, not navigation, dialog answers, page
closure or other input. Expired or denied authority requires current authorized
access, not a different target or credential source.

For timeout, cancellation, transport loss or an unknown action outcome, report
what was dispatched versus what was verified. Observe the site's current state
before deciding what to do next. Do not automatically repeat an effect-bearing
action.
