"""Calendar models and actual SDK request/response contracts, without live Google."""

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from azents.services.google_workspace import calendar
from azents.services.google_workspace.calendar_models import (
    CalendarAttendee,
    CalendarConference,
    CalendarCreateCalendarInput,
    CalendarCreateInput,
    CalendarDeleteInput,
    CalendarEventFields,
    CalendarEventGetInput,
    CalendarEventListInput,
    CalendarFocusTime,
    CalendarFreeBusyInput,
    CalendarInstancesInput,
    CalendarListInput,
    CalendarPatchInput,
    CalendarRsvpInput,
    CalendarStatusCreateInput,
    CalendarStatusDeleteInput,
    CalendarStatusListInput,
    CalendarStatusPatchInput,
    CalendarSuggestInput,
    CalendarTime,
)
from azents.services.google_workspace.transport import (
    GoogleSdkError,
    GoogleSdkLimits,
    GoogleSdkSession,
    GoogleWorkspaceSdk,
)


class _Stream(httpx.SyncByteStream):
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode()

    def __iter__(self) -> Iterator[bytes]:
        yield self.body


async def _run[T](
    operation: Callable[[GoogleSdkSession], T],
    responses: tuple[object, ...],
    requests: list[httpx.Request],
) -> T:
    payloads = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_Stream(next(payloads)),
        )

    sdk = GoogleWorkspaceSdk(
        capacity=1,
        client_factory=lambda proxy, timeout: httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )
    return await sdk.run(
        access_token="fixture",
        limits=GoogleSdkLimits(
            maximum_response_bytes=65536,
            maximum_total_received_bytes=131072,
            maximum_upload_bytes=65536,
            timeout=5,
        ),
        proxy_url=None,
        before_request=lambda: None,
        operation=operation,
    )


def _time(value: str) -> CalendarTime:
    return CalendarTime.model_validate(
        {"date": None, "date_time": value, "time_zone": "Asia/Seoul"}
    )


@pytest.fixture
def event() -> CalendarEventFields:
    return CalendarEventFields(
        summary="Team review",
        description=None,
        location=None,
        start=_time("2026-10-21T09:00:00+09:00"),
        end=_time("2026-10-21T10:00:00+09:00"),
        attendees=(),
        recurrence=(),
        event_type="default",
        guests_can_modify=None,
        guests_can_invite_others=None,
        guests_can_see_other_guests=None,
        focus_time=None,
        out_of_office=None,
        conference=None,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"date": None, "date_time": "2026-10-21T09:00:00", "time_zone": "Asia/Seoul"},
        {"date": None, "date_time": None, "time_zone": None},
        {
            "date": "2026-10-21",
            "date_time": "2026-10-21T09:00:00+09:00",
            "time_zone": None,
        },
        {
            "date": None,
            "date_time": "2026-10-21T09:00:00+09:00",
            "time_zone": "Invalid/Timezone",
        },
    ],
)
def test_calendar_time_requires_exact_date_or_offset_aware_time(
    payload: object,
) -> None:
    with pytest.raises(ValidationError):
        CalendarTime.model_validate(payload)


@pytest.mark.parametrize("end", ["2026-10-21", "2026-10-20"])
def test_all_day_end_is_exclusive_and_after_start(
    event: CalendarEventFields, end: str
) -> None:
    payload = event.model_dump()
    payload.update(
        start={"date": "2026-10-21", "date_time": None, "time_zone": None},
        end={"date": end, "date_time": None, "time_zone": None},
    )
    with pytest.raises(ValidationError, match="exclusive"):
        CalendarEventFields.model_validate(payload)


@pytest.mark.parametrize(
    "recurrence",
    [
        ["RRULE:INVALID"],
        ["RRULE:FREQ=NOT_A_FREQUENCY"],
        ["RRULE:FREQ=DAILY;COUNT=3;UNTIL=20261024T000000Z"],
        ["RRULE:FREQ=DAILY\nATTENDEE:attacker@example.com"],
        ["RDATEjunk:20261022"],
        ["EXDATE;VALUE=DATE:20269999"],
    ],
)
def test_invalid_recurrence_is_rejected_without_expanding(
    event: CalendarEventFields, recurrence: object
) -> None:
    payload = event.model_dump()
    payload["recurrence"] = recurrence
    with pytest.raises(ValidationError):
        CalendarEventFields.model_validate(payload)


def test_valid_all_day_recurrence_and_exceptions_preserve_original_lines(
    event: CalendarEventFields,
) -> None:
    payload = event.model_dump()
    payload.update(
        start={"date": "2026-10-21", "date_time": None, "time_zone": "Asia/Seoul"},
        end={"date": "2026-10-22", "date_time": None, "time_zone": "Asia/Seoul"},
        recurrence=[
            "RRULE:FREQ=DAILY;COUNT=3",
            "EXDATE;VALUE=DATE:20261022",
            "RDATE;VALUE=DATE:20261025",
        ],
    )
    result = CalendarEventFields.model_validate(payload)
    assert result.recurrence == tuple(payload["recurrence"])


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"start": {"date": "2026-10-21", "date_time": None, "time_zone": None}},
        {"recurrence": ["RRULE:FREQ=DAILY"]},
        {"description": None},
        {"unexpected": "unknown field"},
    ],
)
def test_patch_is_presence_aware_and_rejects_invalid_changes(changes: object) -> None:
    with pytest.raises(ValidationError):
        CalendarPatchInput.model_validate(
            {
                "calendar_id": "primary",
                "event_id": "event",
                "changes": changes,
                "send_updates": "all",
            }
        )


async def test_create_event_preserves_timezones_attendees_conference_and_notifications(
    event: CalendarEventFields,
) -> None:
    payload = event.model_dump()
    payload.update(
        attendees=[
            CalendarAttendee(
                email="reader@example.com", display_name="Reader", optional=False
            ).model_dump()
        ],
        conference=CalendarConference(
            request_id="fixture-conference-request"
        ).model_dump(),
        recurrence=["RRULE:FREQ=WEEKLY;COUNT=2"],
    )
    fields = CalendarEventFields.model_validate(payload)
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: calendar.create_event(
            session,
            CalendarCreateInput(
                calendar_id="primary", event=fields, send_updates="all"
            ),
        ),
        ({"id": "created", "htmlLink": "https://calendar.google.com/event"},),
        requests,
    )
    assert result.id == "created"
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/calendar/v3/calendars/primary/events"
    assert request.url.params["sendUpdates"] == "all"
    assert request.url.params["conferenceDataVersion"] == "1"
    body = json.loads(request.content)
    assert body["start"] == {
        "dateTime": "2026-10-21T09:00:00+09:00",
        "timeZone": "Asia/Seoul",
    }
    assert body["attendees"] == [
        {"email": "reader@example.com", "displayName": "Reader", "optional": False}
    ]
    assert (
        body["conferenceData"]["createRequest"]["requestId"]
        == "fixture-conference-request"
    )
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=2"]


@pytest.mark.parametrize("allowed", [True, False, None])
async def test_create_guest_privileges_preserve_explicit_values_and_provider_defaults(
    allowed: bool | None,
    event: CalendarEventFields,
) -> None:
    payload = event.model_dump()
    payload.update(
        guests_can_modify=allowed,
        guests_can_invite_others=allowed,
        guests_can_see_other_guests=allowed,
    )
    fields = CalendarEventFields.model_validate(payload)
    requests: list[httpx.Request] = []
    response = {"id": "created"}
    if allowed is not None:
        response.update(
            guestsCanModify=allowed,
            guestsCanInviteOthers=allowed,
            guestsCanSeeOtherGuests=allowed,
        )
    result = await _run(
        lambda session: calendar.create_event(
            session,
            CalendarCreateInput(
                calendar_id="primary", event=fields, send_updates="none"
            ),
        ),
        (response,),
        requests,
    )
    body = json.loads(requests[0].content)
    for key in ("guestsCanModify", "guestsCanInviteOthers", "guestsCanSeeOtherGuests"):
        if allowed is None:
            assert key not in body
        else:
            assert body[key] is allowed
        assert result.model_dump(by_alias=True)[key] is allowed
    assert len(requests) == 1


@pytest.mark.parametrize("allowed", [True, False])
async def test_patch_can_change_guest_privileges_without_replacing_attendees(
    allowed: bool,
) -> None:
    requests: list[httpx.Request] = []
    value = CalendarPatchInput.model_validate(
        {
            "calendar_id": "primary",
            "event_id": "event",
            "changes": {
                "guests_can_modify": allowed,
                "guests_can_invite_others": allowed,
                "guests_can_see_other_guests": allowed,
            },
            "send_updates": "none",
        }
    )
    await _run(
        lambda session: calendar.patch_event(session, value),
        ({"id": "event"},),
        requests,
    )
    assert json.loads(requests[0].content) == {
        "guestsCanModify": allowed,
        "guestsCanInviteOthers": allowed,
        "guestsCanSeeOtherGuests": allowed,
    }
    assert len(requests) == 1


@pytest.mark.parametrize(
    "field",
    ["guests_can_modify", "guests_can_invite_others", "guests_can_see_other_guests"],
)
@pytest.mark.parametrize("invalid", [None, "false", 0, 1])
def test_patch_guest_privileges_require_explicit_booleans(
    field: str, invalid: object
) -> None:
    with pytest.raises(ValidationError):
        CalendarPatchInput.model_validate(
            {
                "calendar_id": "primary",
                "event_id": "event",
                "changes": {field: invalid},
                "send_updates": "none",
            }
        )


async def test_patch_omission_keeps_other_fields_and_explicit_empty_text_clears() -> (
    None
):
    requests: list[httpx.Request] = []
    value = CalendarPatchInput.model_validate(
        {
            "calendar_id": "primary",
            "event_id": "occurrence-id",
            "changes": {"description": ""},
            "send_updates": "none",
        }
    )
    result = await _run(
        lambda session: calendar.patch_event(session, value),
        ({"id": "occurrence-id"},),
        requests,
    )
    assert result.id == "occurrence-id"
    assert requests[0].method == "PATCH"
    assert requests[0].url.path.endswith("/events/occurrence-id")
    assert json.loads(requests[0].content) == {"description": ""}
    assert requests[0].url.params["sendUpdates"] == "none"


async def test_rsvp_changes_only_self_with_explicit_notifications() -> None:
    requests: list[httpx.Request] = []
    value = CalendarRsvpInput(
        calendar_id="primary",
        event_id="event",
        response_status="declined",
        comment="Unavailable",
        send_updates="all",
    )
    await _run(
        lambda session: calendar.respond_event(session, value),
        (
            {
                "id": "event",
                "attendees": [
                    {"email": "other@example.com"},
                    {"email": "connected@example.com", "self": True},
                ],
            },
            {"id": "event"},
        ),
        requests,
    )
    assert len(requests) == 2
    assert requests[0].method == "GET" and requests[1].method == "PATCH"
    assert json.loads(requests[1].content) == {
        "attendeesOmitted": True,
        "attendees": [
            {
                "email": "connected@example.com",
                "responseStatus": "declined",
                "comment": "Unavailable",
            }
        ],
    }
    assert requests[1].url.params["sendUpdates"] == "all"


async def test_rsvp_without_verified_self_attendee_does_not_send_patch() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: calendar.respond_event(
                session,
                CalendarRsvpInput(
                    calendar_id="primary",
                    event_id="event",
                    response_status="accepted",
                    comment=None,
                    send_updates="all",
                ),
            ),
            ({"id": "event", "attendees": [{"email": "other@example.com"}]},),
            requests,
        )
    assert error.value.code == "self_attendee_unavailable"
    assert len(requests) == 1


async def test_freebusy_returns_intervals_not_event_content() -> None:
    requests: list[httpx.Request] = []
    value = CalendarFreeBusyInput.model_validate(
        {
            "calendars": ["primary"],
            "time_min": "2026-10-21T00:00:00Z",
            "time_max": "2026-10-21T04:00:00Z",
            "time_zone": "Asia/Seoul",
        }
    )
    result = await _run(
        lambda session: calendar.query_freebusy(session, value),
        (
            {
                "timeMin": "2026-10-21T00:00:00Z",
                "timeMax": "2026-10-21T04:00:00Z",
                "calendars": {
                    "primary": {
                        "busy": [
                            {
                                "start": "2026-10-21T01:00:00Z",
                                "end": "2026-10-21T02:00:00Z",
                            }
                        ],
                        "description": "private event content",
                    }
                },
                "items": [{"description": "private event content"}],
            },
        ),
        requests,
    )
    assert requests[0].url.path == "/calendar/v3/freeBusy"
    assert len(result.calendars["primary"].busy) == 1
    assert "private event content" not in result.model_dump_json()
    assert json.loads(requests[0].content)["timeZone"] == "Asia/Seoul"


async def test_time_suggestions_merge_overlapping_busy_intervals_across_calendars() -> (
    None
):
    value = CalendarSuggestInput.model_validate(
        {
            "calendars": ["one", "two"],
            "time_min": "2026-10-21T00:00:00Z",
            "time_max": "2026-10-21T04:00:00Z",
            "time_zone": None,
            "duration_minutes": 60,
            "maximum_suggestions": 3,
        }
    )
    result = await _run(
        lambda session: calendar.suggest_time(session, value),
        (
            {
                "timeMin": "2026-10-21T00:00:00Z",
                "timeMax": "2026-10-21T04:00:00Z",
                "calendars": {
                    "one": {
                        "busy": [
                            {
                                "start": "2026-10-21T01:00:00Z",
                                "end": "2026-10-21T02:00:00Z",
                            }
                        ]
                    },
                    "two": {
                        "busy": [
                            {
                                "start": "2026-10-21T01:30:00Z",
                                "end": "2026-10-21T03:00:00Z",
                            }
                        ]
                    },
                },
            },
        ),
        [],
    )
    assert [interval.start.hour for interval in result.suggestions] == [0, 3]


@pytest.mark.parametrize(
    "calendars", [{}, {"primary": {"errors": [{"reason": "notFound"}]}}]
)
async def test_incomplete_availability_is_not_claimed_free(calendars: object) -> None:
    value = CalendarSuggestInput.model_validate(
        {
            "calendars": ["primary"],
            "time_min": "2026-10-21T00:00:00Z",
            "time_max": "2026-10-21T04:00:00Z",
            "time_zone": None,
            "duration_minutes": 60,
            "maximum_suggestions": 3,
        }
    )
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: calendar.suggest_time(session, value),
            (
                {
                    "timeMin": "2026-10-21T00:00:00Z",
                    "timeMax": "2026-10-21T04:00:00Z",
                    "calendars": calendars,
                },
            ),
            [],
        )
    assert error.value.code == "availability_incomplete"


async def test_calendar_list_and_event_pagination_remain_explicit() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: calendar.list_calendars(
            session, CalendarListInput(page_token="cursor", page_size=10)
        ),
        ({"items": [{"id": "primary", "summary": "Main"}], "nextPageToken": "next"},),
        requests,
    )
    assert result.next_page_token == "next"
    assert len(requests) == 1
    assert requests[0].url.params["pageToken"] == "cursor"
    assert requests[0].url.params["maxResults"] == "10"


async def test_event_search_and_instance_target_are_exact() -> None:
    requests: list[httpx.Request] = []
    value = CalendarEventListInput(
        calendar_id="shared@example.com",
        page_token=None,
        page_size=20,
        time_min=None,
        time_max=None,
        query="planning",
        expand_recurring=True,
        event_types=("default",),
    )
    result = await _run(
        lambda session: calendar.list_events(session, value),
        (
            {
                "items": [{"id": "instance", "recurringEventId": "master"}],
                "nextPageToken": "next",
            },
        ),
        requests,
    )
    assert result.items[0].recurring_event_id == "master"
    assert requests[0].url.params["singleEvents"] == "true"
    assert requests[0].url.params["q"] == "planning"
    instance_requests: list[httpx.Request] = []
    await _run(
        lambda session: calendar.list_instances(
            session,
            CalendarInstancesInput(
                calendar_id="primary",
                event_id="master",
                page_token=None,
                page_size=20,
                time_min=None,
                time_max=None,
            ),
        ),
        ({"items": []},),
        instance_requests,
    )
    assert instance_requests[0].url.path.endswith("/events/master/instances")


async def test_focus_time_creation_preserves_decline_and_chat_effects(
    event: CalendarEventFields,
) -> None:
    payload = event.model_dump()
    payload.update(
        event_type="focusTime",
        focus_time=CalendarFocusTime(
            auto_decline_mode="declineOnlyNewConflictingInvitations",
            chat_status="doNotDisturb",
            decline_message="Focus session",
        ).model_dump(),
    )
    fields = CalendarEventFields.model_validate(payload)
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: calendar.create_status_event(
            session,
            CalendarStatusCreateInput(
                calendar_id="primary", event=fields, send_updates="all"
            ),
        ),
        (
            {
                "id": "focus",
                "eventType": "focusTime",
                "focusTimeProperties": {
                    "autoDeclineMode": "declineOnlyNewConflictingInvitations",
                    "chatStatus": "doNotDisturb",
                    "declineMessage": "Focus session",
                },
            },
        ),
        requests,
    )
    assert (
        result.focus_time is not None
        and result.focus_time.chat_status == "doNotDisturb"
    )
    assert (
        json.loads(requests[0].content)["focusTimeProperties"]["autoDeclineMode"]
        == "declineOnlyNewConflictingInvitations"
    )


@pytest.mark.parametrize("target", ["default", "fromGmail"])
async def test_status_delete_cannot_delete_an_ordinary_event(target: str) -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: calendar.delete_status_event(
                session,
                CalendarStatusDeleteInput(
                    calendar_id="primary", event_id="event", send_updates="all"
                ),
            ),
            ({"id": "event", "eventType": target},),
            requests,
        )
    assert error.value.code == "status_event_unavailable"
    assert len(requests) == 1 and requests[0].method == "GET"


@pytest.mark.parametrize("model", [CalendarStatusDeleteInput, CalendarStatusPatchInput])
def test_status_changes_reject_nonprimary_targets_before_sdk(
    model: type[BaseModel],
) -> None:
    payload: dict[str, object] = {
        "calendar_id": "secondary",
        "event_id": "event",
        "send_updates": "all",
    }
    if model is CalendarStatusPatchInput:
        payload["changes"] = {"summary": "changed"}
    with pytest.raises(ValidationError, match="primary"):
        model.model_validate(payload)


async def test_wrong_get_event_identity_cannot_drive_a_followup_rsvp() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: calendar.respond_event(
                session,
                CalendarRsvpInput(
                    calendar_id="primary",
                    event_id="expected",
                    response_status="accepted",
                    comment=None,
                    send_updates="all",
                ),
            ),
            (
                {
                    "id": "different",
                    "attendees": [
                        {"email": "connected@example.com", "self": True},
                    ],
                },
            ),
            requests,
        )
    assert error.value.code == "event_identity_mismatch"
    assert len(requests) == 1 and requests[0].method == "GET"


async def test_secondary_calendar_creation_needs_no_unrelated_api_call() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: calendar.create_calendar(
            session,
            CalendarCreateCalendarInput(
                summary="Project", description=None, time_zone="Asia/Seoul"
            ),
        ),
        ({"id": "new-calendar", "summary": "Project", "timeZone": "Asia/Seoul"},),
        requests,
    )
    assert result.id == "new-calendar"
    assert len(requests) == 1 and requests[0].url.path == "/calendar/v3/calendars"
    assert json.loads(requests[0].content) == {
        "summary": "Project",
        "timeZone": "Asia/Seoul",
    }


@pytest.mark.parametrize(
    "model",
    [
        CalendarListInput,
        CalendarEventListInput,
        CalendarEventGetInput,
        CalendarInstancesInput,
        CalendarFreeBusyInput,
        CalendarSuggestInput,
        CalendarCreateInput,
        CalendarPatchInput,
        CalendarDeleteInput,
        CalendarRsvpInput,
        CalendarCreateCalendarInput,
        CalendarStatusCreateInput,
        CalendarStatusListInput,
        CalendarStatusPatchInput,
        CalendarStatusDeleteInput,
    ],
)
def test_calendar_tool_schemas_are_top_level_objects(model: type[BaseModel]) -> None:
    schema = model.model_json_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "oneOf" not in schema
