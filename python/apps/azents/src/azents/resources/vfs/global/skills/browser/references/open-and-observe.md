# Open and Observe

The examples name a tool and its arguments. Send the `arguments` object through
that tool. Replace example identities with values from current results.

## Availability and task selection

Inspect the current Session without selecting an invented target:

```json
{"tool":"browser_observe","arguments":{"view":"status"}}
```

Open a task when there is no appropriate existing activity:

```json
{"tool":"browser_open","arguments":{"url":"https://example.test/","label":"Review delivery"}}
```

Supply a current `task_id` to add a page to that task. An allocated page does not
prove its navigation succeeded; inspect the result and current page state.
Opening a separate task does not create a separate login profile within the same
Session.

`page.id`, `page.task_id` and `page.resource_incarnation` form the target. Keep
popup targets from `popup` separately from the original page. A replaced Runner,
closed resource or changed incarnation invalidates the old target.

## Select the observation

Read rendered content with bounded readable text:

```json
{"tool":"browser_observe","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","view":"glance","max_characters":16000}}
```

Before an element action, obtain current references:

```json
{"tool":"browser_observe","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","view":"dom"}}
```

Each entry in `refs` supplies its `id`, `observation_id` and `frame_id`. Select the
entry that actually identifies the intended control. Labels can be ambiguous;
use the surrounding page and a visual observation where necessary.

For an observed child frame, supply its current frame ID:

```json
{"tool":"browser_observe","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","frame_id":"FRAME","view":"raw_dom","max_characters":12000}}
```

Omit `frame_id` or use null for the main frame. Navigation can replace frames and
invalidate their references. One body observation is not a complete export of
all frames, closed Shadow DOM, virtualized content or hidden application state.

Respect `truncated` and the reported source/scope. Narrow the task or make another
explicit observation when needed. Input values and unsafe attributes are
structurally excluded from ordinary DOM output; ordinary visible text remains
page content, including text the site echoes after a form submission.

For canvas, layout or other visual evidence, use `view="image"` and the capture
reference. The returned image is actual model input, not a textual screenshot
description.
