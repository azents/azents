# Scheduled Task Schedule Interpretation

Translate natural-language timing into one canonical one-time or recurring
schedule.

## Resolution order

1. Determine whether the request is one-time or recurring.
2. Determine whether it is duration-relative or calendar-based.
3. Resolve timezone only when calendar interpretation requires it.
4. Produce the canonical schedule fields.
5. Validate the result before creation.

## One-time schedules

Use one timezone-bearing RFC 3339 timestamp. The timestamp must contain `Z` or an
explicit UTC offset. Reject a timezone-less timestamp.

Reject a newly registered one-time schedule whose instant is earlier than the
registration time.

### Duration-relative request

For a request such as "one hour from now":

- derive the instant from the current time;
- do not ask for the user's timezone; and
- serialize the resulting instant as timezone-bearing RFC 3339.

### Calendar-time request

For a request such as "tomorrow at 9 AM":

1. Use the timezone explicitly stated by the user.
2. Otherwise, use a timezone reliably established by user or conversation
   context.
3. Ask for the timezone only if it remains unknown.

Do not treat a guessed geographic location as reliable timezone evidence when
the context is ambiguous.

## Recurring schedules

Use one standard five-field cron expression and one IANA timezone identifier.
Do not generate seconds or year fields.

A recurring calendar schedule always requires an IANA timezone. Infer it from
reliable context or ask the user when it is unknown.

## Ambiguity handling

Ask only when ambiguity materially affects the execution instant or recurrence.

Clarification is required when, for example:

- "every morning" has no interpretable time;
- "Friday" could materially mean one-time or recurring work;
- a calendar time has no reliably inferable timezone; or
- the requested recurrence cannot be represented accurately.

Do not ask when ordinary language has one reasonable interpretation and the
difference would not materially affect the request.

## Examples

### Relative one-time request

User request:

> Check the deployment again in one hour.

Do not ask for timezone. Add one hour to the current instant and create a
one-time RFC 3339 schedule.

### Calendar one-time request with known context

User request:

> Check the deployment tomorrow at 9 AM.

Use the reliably established user timezone without asking the user to confirm it
again. Convert the calendar time into a timezone-bearing RFC 3339 timestamp.

### Calendar one-time request with unknown timezone

User request:

> Check the deployment tomorrow at 9 AM.

Ask one focused question requesting the timezone. Do not create the Task until
the instant can be determined.

### Recurring request

User request:

> Every weekday at 9 AM, review yesterday's critical errors and summarize their
> likely causes and recommended actions.

Resolve an IANA timezone and produce a five-field cron expression. Preserve the
work scope, completion conditions, and expected summary in the objective. Do not
ask additional questions when the request is already actionable.
