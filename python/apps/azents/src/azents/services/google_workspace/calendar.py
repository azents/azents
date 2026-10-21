"""Typed Calendar SDK methods; account features and resource ACLs remain Google's."""

from datetime import timedelta
from typing import TYPE_CHECKING

from azents.services.google_workspace.calendar_models import (
    CalendarAttendee,
    CalendarBusyInterval,
    CalendarConference,
    CalendarCreateCalendarInput,
    CalendarCreateInput,
    CalendarDeleteInput,
    CalendarEntryResult,
    CalendarEventFields,
    CalendarEventGetInput,
    CalendarEventListInput,
    CalendarEventListResult,
    CalendarEventResult,
    CalendarFocusTime,
    CalendarFreeBusyInput,
    CalendarFreeBusyResult,
    CalendarInstancesInput,
    CalendarListInput,
    CalendarListResult,
    CalendarOutOfOffice,
    CalendarPatchInput,
    CalendarRsvpInput,
    CalendarStatusCreateInput,
    CalendarStatusDeleteInput,
    CalendarStatusListInput,
    CalendarStatusPatchInput,
    CalendarSuggestInput,
    CalendarSuggestions,
    CalendarTime,
)
from azents.services.google_workspace.transport import (
    GoogleEmptyResponse,
    GoogleSdkError,
    GoogleSdkSession,
)

if TYPE_CHECKING:
    from googleapiclient._apis.calendar.v3.schemas import (
        Calendar,
        ConferenceData,
        Event,
        EventAttendee,
        EventDateTime,
        EventFocusTimeProperties,
        EventOutOfOfficeProperties,
        FreeBusyRequest,
    )


def _time(value: CalendarTime) -> "EventDateTime":
    result: EventDateTime = {}
    if value.date is not None:
        result["date"] = value.date.isoformat()
    if value.date_time is not None:
        result["dateTime"] = value.date_time.isoformat()
    if value.time_zone is not None:
        result["timeZone"] = value.time_zone
    return result


def _attendee(value: CalendarAttendee) -> "EventAttendee":
    result: EventAttendee = {"email": value.email, "optional": value.optional}
    if value.display_name is not None:
        result["displayName"] = value.display_name
    return result


def _focus(value: CalendarFocusTime) -> "EventFocusTimeProperties":
    result: EventFocusTimeProperties = {
        "autoDeclineMode": value.auto_decline_mode,
        "chatStatus": value.chat_status,
    }
    if value.decline_message is not None:
        result["declineMessage"] = value.decline_message
    return result


def _out_of_office(value: CalendarOutOfOffice) -> "EventOutOfOfficeProperties":
    result: EventOutOfOfficeProperties = {"autoDeclineMode": value.auto_decline_mode}
    if value.decline_message is not None:
        result["declineMessage"] = value.decline_message
    return result


def _conference(value: CalendarConference) -> "ConferenceData":
    return {
        "createRequest": {
            "requestId": value.request_id,
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def _event(value: CalendarEventFields) -> "Event":
    result: Event = {
        "summary": value.summary,
        "start": _time(value.start),
        "end": _time(value.end),
        "attendees": [_attendee(attendee) for attendee in value.attendees],
        "recurrence": list(value.recurrence),
        "eventType": value.event_type,
    }
    if value.description is not None:
        result["description"] = value.description
    if value.location is not None:
        result["location"] = value.location
    if value.focus_time is not None:
        result["focusTimeProperties"] = _focus(value.focus_time)
    if value.out_of_office is not None:
        result["outOfOfficeProperties"] = _out_of_office(value.out_of_office)
    if value.conference is not None:
        result["conferenceData"] = _conference(value.conference)
    return result


def list_calendars(
    session: GoogleSdkSession, value: CalendarListInput
) -> CalendarListResult:
    request = session.calendar.calendarList().list(
        maxResults=value.page_size, pageToken=value.page_token
    )
    return session.decode(CalendarListResult, request)


def list_events(
    session: GoogleSdkSession, value: CalendarEventListInput
) -> CalendarEventListResult:
    request = session.calendar.events().list(
        calendarId=value.calendar_id,
        maxResults=value.page_size,
        pageToken=value.page_token,
        timeMin=None if value.time_min is None else value.time_min.isoformat(),
        timeMax=None if value.time_max is None else value.time_max.isoformat(),
        q=value.query,
        singleEvents=value.expand_recurring,
        eventTypes=list(value.event_types) if value.event_types else None,
        orderBy="startTime" if value.expand_recurring else None,
    )
    return session.decode(CalendarEventListResult, request)


def get_event(
    session: GoogleSdkSession, value: CalendarEventGetInput
) -> CalendarEventResult:
    result = session.decode(
        CalendarEventResult,
        session.calendar.events().get(
            calendarId=value.calendar_id, eventId=value.event_id
        ),
    )
    if result.id != value.event_id:
        raise GoogleSdkError("event_identity_mismatch", dispatched=True, status=None)
    return result


def list_instances(
    session: GoogleSdkSession, value: CalendarInstancesInput
) -> CalendarEventListResult:
    request = session.calendar.events().instances(
        calendarId=value.calendar_id,
        eventId=value.event_id,
        maxResults=value.page_size,
        pageToken=value.page_token,
        timeMin=None if value.time_min is None else value.time_min.isoformat(),
        timeMax=None if value.time_max is None else value.time_max.isoformat(),
    )
    return session.decode(CalendarEventListResult, request)


def query_freebusy(
    session: GoogleSdkSession, value: CalendarFreeBusyInput
) -> CalendarFreeBusyResult:
    body: FreeBusyRequest = {
        "items": [{"id": calendar} for calendar in value.calendars],
        "timeMin": value.time_min.isoformat(),
        "timeMax": value.time_max.isoformat(),
        "calendarExpansionMax": 50,
    }
    if value.time_zone is not None:
        body["timeZone"] = value.time_zone
    return session.decode(
        CalendarFreeBusyResult, session.calendar.freebusy().query(body=body)
    )


def suggest_time(
    session: GoogleSdkSession, value: CalendarSuggestInput
) -> CalendarSuggestions:
    availability = query_freebusy(session, value)
    if availability.time_min > value.time_min or availability.time_max < value.time_max:
        raise GoogleSdkError("availability_incomplete", dispatched=True, status=None)
    intervals: list[CalendarBusyInterval] = []
    for calendar_id in value.calendars:
        calendar = availability.calendars.get(calendar_id)
        if calendar is None or calendar.errors:
            raise GoogleSdkError(
                "availability_incomplete", dispatched=True, status=None
            )
        intervals.extend(calendar.busy)
    duration = timedelta(minutes=value.duration_minutes)
    cursor = value.time_min
    suggestions: list[CalendarBusyInterval] = []
    for interval in sorted(intervals, key=lambda busy: busy.start):
        session.require_current()
        while (
            cursor + duration <= min(interval.start, value.time_max)
            and len(suggestions) < value.maximum_suggestions
        ):
            suggestions.append(
                CalendarBusyInterval(start=cursor, end=cursor + duration)
            )
            cursor += duration
        cursor = max(cursor, interval.end)
        if cursor >= value.time_max or len(suggestions) >= value.maximum_suggestions:
            break
    while (
        cursor + duration <= value.time_max
        and len(suggestions) < value.maximum_suggestions
    ):
        suggestions.append(CalendarBusyInterval(start=cursor, end=cursor + duration))
        cursor += duration
    return CalendarSuggestions(suggestions=tuple(suggestions))


def create_event(
    session: GoogleSdkSession, value: CalendarCreateInput
) -> CalendarEventResult:
    request = session.calendar.events().insert(
        calendarId=value.calendar_id,
        body=_event(value.event),
        sendUpdates=value.send_updates,
        conferenceDataVersion=1 if value.event.conference is not None else None,
    )
    return session.decode(CalendarEventResult, request)


def patch_event(
    session: GoogleSdkSession, value: CalendarPatchInput
) -> CalendarEventResult:
    changes = value.changes
    body: Event = {}
    if "summary" in changes:
        body["summary"] = changes["summary"]
    if "description" in changes:
        body["description"] = changes["description"]
    if "location" in changes:
        body["location"] = changes["location"]
    if "start" in changes:
        body["start"] = _time(changes["start"])
    if "end" in changes:
        body["end"] = _time(changes["end"])
    if "attendees" in changes:
        body["attendees"] = [_attendee(attendee) for attendee in changes["attendees"]]
    if "recurrence" in changes:
        body["recurrence"] = list(changes["recurrence"])
    if "focus_time" in changes:
        body["focusTimeProperties"] = _focus(changes["focus_time"])
    if "out_of_office" in changes:
        body["outOfOfficeProperties"] = _out_of_office(changes["out_of_office"])
    if "conference" in changes:
        body["conferenceData"] = _conference(changes["conference"])
    request = session.calendar.events().patch(
        calendarId=value.calendar_id,
        eventId=value.event_id,
        body=body,
        sendUpdates=value.send_updates,
        conferenceDataVersion=1 if "conference" in changes else None,
    )
    return session.decode(CalendarEventResult, request)


def delete_event(session: GoogleSdkSession, value: CalendarDeleteInput) -> None:
    session.decode(
        GoogleEmptyResponse,
        session.calendar.events().delete(
            calendarId=value.calendar_id,
            eventId=value.event_id,
            sendUpdates=value.send_updates,
        ),
    )


def respond_event(
    session: GoogleSdkSession, value: CalendarRsvpInput
) -> CalendarEventResult:
    event = get_event(
        session,
        CalendarEventGetInput(calendar_id=value.calendar_id, event_id=value.event_id),
    )
    self_attendees = [
        attendee
        for attendee in event.attendees or ()
        if attendee.self_attendee and attendee.email is not None
    ]
    if len(self_attendees) != 1:
        raise GoogleSdkError("self_attendee_unavailable", dispatched=True, status=None)
    email = self_attendees[0].email
    if email is None:
        raise AssertionError("Validated self attendee email is missing.")
    attendee: EventAttendee = {"email": email, "responseStatus": value.response_status}
    if value.comment is not None:
        attendee["comment"] = value.comment
    body: Event = {"attendees": [attendee], "attendeesOmitted": True}
    request = session.calendar.events().patch(
        calendarId=value.calendar_id,
        eventId=value.event_id,
        body=body,
        sendUpdates=value.send_updates,
    )
    return session.decode(CalendarEventResult, request)


def create_calendar(
    session: GoogleSdkSession, value: CalendarCreateCalendarInput
) -> CalendarEntryResult:
    body: Calendar = {"summary": value.summary, "timeZone": value.time_zone}
    if value.description is not None:
        body["description"] = value.description
    return session.decode(
        CalendarEntryResult, session.calendar.calendars().insert(body=body)
    )


def list_status_events(
    session: GoogleSdkSession, value: CalendarStatusListInput
) -> CalendarEventListResult:
    return list_events(session, value)


def create_status_event(
    session: GoogleSdkSession, value: CalendarStatusCreateInput
) -> CalendarEventResult:
    return create_event(session, value)


def _require_status_event(
    session: GoogleSdkSession, value: CalendarEventGetInput
) -> CalendarEventResult:
    if value.calendar_id != "primary":
        raise GoogleSdkError(
            "status_calendar_unavailable", dispatched=False, status=None
        )
    event = get_event(session, value)
    if event.event_type not in {"focusTime", "outOfOffice"}:
        raise GoogleSdkError("status_event_unavailable", dispatched=True, status=None)
    return event


def patch_status_event(
    session: GoogleSdkSession, value: CalendarStatusPatchInput
) -> CalendarEventResult:
    event = _require_status_event(session, value)
    if (
        "focus_time" in value.changes
        and event.event_type != "focusTime"
        or "out_of_office" in value.changes
        and event.event_type != "outOfOffice"
    ):
        raise GoogleSdkError("status_properties_mismatch", dispatched=True, status=None)
    return patch_event(session, value)


def delete_status_event(
    session: GoogleSdkSession, value: CalendarStatusDeleteInput
) -> None:
    _require_status_event(session, value)
    delete_event(session, value)
