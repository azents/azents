# Scheduled Task Creation Contexts

Use the scenario matching the specific user message that requests the Task.

## Ordinary Session request

Set `channel_id` to `null`.

Create the Task for the current AgentSession without requesting or supplying a
different Session identifier. The Task's progress and result remain available
through the Session experience.

## Request from an External Channel conversation

Use the exact opaque handle associated with the requesting message as
`channel_id`.

The value must be identical to the value supplied as `channel_action.binding`.
Pass it unchanged. Preserve the exact conversation scope represented by the
handle, and do not inspect or reconstruct provider-native identifiers.

## Request from a nested conversation

Use the handle for the exact nested conversation from which the request
originated. Do not replace it with the parent conversation's handle.

Existing External Channel presentation behavior owns any provider-native parent
surfacing.

## Another connected channel explicitly requested

An explicit target overrides the source-channel default.

Use the requested channel's opaque handle only when model-visible context
reliably maps the user's description to exactly one connected channel. Do not
change the current AgentSession.

If the target cannot be mapped uniquely, ask one focused clarification rather
than guessing.

## Multiple available channels

Use the origin of the specific scheduling request as the default.

Do not assume that the most recently active handle, first available handle, or a
previously discussed channel is the intended target.

When the user explicitly names another target, use that target only if it maps
reliably to one available handle.

## Unavailable or unconnected target

Do not:

- use the source channel instead;
- use another connected channel;
- create a Session-only Task; or
- reconstruct a provider-native channel identifier.

Report that the requested target is unavailable or unconnected. Let the existing
External Channel setup and authorization flows establish the target before
retrying creation.

## Channel validation failure

Treat the Scheduled Task tool as authoritative for channel connection, Session
ownership, and authorization.

If the tool rejects `channel_id`, report the rejection and stop. Do not retry with
`null` or another handle unless the user explicitly selects a new target.

## Dedicated Session requested

Explain that Scheduled Task Agent tools always use the current AgentSession.

Do not silently create the Task in the current Session when the user specifically
requires a separate persistent Session. Direct the user to the product flow that
can create or select a dedicated Session.

## Explanation-only request

When the user asks how creation would work, explain the applicable target,
objective, schedule, and clarification behavior without calling
`add_scheduled_task`.
