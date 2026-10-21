"""Closed Calendar tool inputs and bounded provider projections."""

from datetime import date as Date
from datetime import datetime
from datetime import time as Time
from typing import Annotated, Literal, Self, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.parser import isoparse
from dateutil.rrule import rrulestr
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
    with_config,
)

CalendarId = Annotated[
    str, StringConstraints(min_length=1, max_length=1024, pattern=r"^[^\r\n\x00]+$")
]
EventId = Annotated[
    str, StringConstraints(min_length=1, max_length=1024, pattern=r"^[^\r\n\x00]+$")
]
SendUpdates = Literal["all", "externalOnly", "none"]
EventType = Literal["default", "outOfOffice", "focusTime"]
ResponseStatus = Literal["accepted", "declined", "tentative", "needsAction"]
AutoDecline = Literal[
    "declineNone",
    "declineAllConflictingInvitations",
    "declineOnlyNewConflictingInvitations",
]


class CalendarInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def require_timezone(value: str | None) -> str | None:
    if value is not None:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            raise ValueError("Calendar timezone must be an IANA timezone.") from None
    return value


class CalendarTime(CalendarInput):
    date: Date | None
    date_time: AwareDatetime | None
    time_zone: str | None

    _timezone = field_validator("time_zone")(require_timezone)

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if (self.date is None) == (self.date_time is None):
            raise ValueError(
                "Specify exactly one calendar date or offset-aware datetime."
            )
        return self


def require_time_range(
    start: CalendarTime, end: CalendarTime, *, recurring: bool
) -> None:
    if start.date is not None:
        if end.date is None or end.date <= start.date:
            raise ValueError("All-day end date must be exclusive and after the start.")
    elif start.date_time is not None:
        if end.date_time is None or end.date_time <= start.date_time:
            raise ValueError("Event end must be after the offset-aware start.")
    if recurring and (start.time_zone is None or end.time_zone is None):
        raise ValueError("Recurring events require explicit IANA start/end timezones.")


def require_recurrence(value: tuple[str, ...], start: CalendarTime) -> None:
    """Parse bounded recurrence syntax without expanding any occurrence series."""
    reference = (
        start.date_time
        if start.date_time is not None
        else datetime.combine(start.date, Time.min)
        if start.date is not None
        else None
    )
    if reference is None:
        raise ValueError("Recurrence requires a valid start.")
    for line in value:
        kind, separator, content = line.partition(":")
        if not separator or not content:
            raise ValueError("Invalid calendar recurrence line.")
        try:
            if kind in {"RRULE", "EXRULE"}:
                if "COUNT=" in content and "UNTIL=" in content:
                    raise ValueError("COUNT and UNTIL cannot be combined.")
                rrulestr(line, dtstart=reference)
            else:
                name, *parameters = kind.split(";")
                if name not in {"RDATE", "EXDATE"}:
                    raise ValueError("Unsupported recurrence property.")
                date_only = False
                for parameter in parameters:
                    if parameter == "VALUE=DATE":
                        date_only = True
                    elif parameter == "VALUE=DATE-TIME":
                        pass
                    elif parameter.startswith("TZID="):
                        require_timezone(parameter.removeprefix("TZID="))
                    else:
                        raise ValueError("Unsupported recurrence parameter.")
                for date_value in content.split(","):
                    if date_only:
                        datetime.strptime(date_value, "%Y%m%d")
                    else:
                        isoparse(date_value)
        except ValueError, TypeError, OverflowError:
            raise ValueError("Invalid calendar recurrence syntax.") from None


class CalendarAttendee(CalendarInput):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@<>]+@[^\s@<>]+$")
    display_name: str | None = Field(max_length=1024)
    optional: bool = Field(strict=True)


class CalendarFocusTime(CalendarInput):
    auto_decline_mode: AutoDecline
    chat_status: Literal["available", "doNotDisturb"]
    decline_message: str | None = Field(max_length=8192)


class CalendarOutOfOffice(CalendarInput):
    auto_decline_mode: AutoDecline
    decline_message: str | None = Field(max_length=8192)


class CalendarConference(CalendarInput):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class CalendarEventFields(CalendarInput):
    summary: str = Field(max_length=4096)
    description: str | None = Field(max_length=65536)
    location: str | None = Field(max_length=4096)
    start: CalendarTime
    end: CalendarTime
    attendees: tuple[CalendarAttendee, ...] = Field(max_length=200)
    recurrence: tuple[str, ...] = Field(max_length=32)
    event_type: EventType
    focus_time: CalendarFocusTime | None
    out_of_office: CalendarOutOfOffice | None
    conference: CalendarConference | None

    @field_validator("recurrence")
    @classmethod
    def validate_recurrence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for rule in value:
            if (
                len(rule) > 4096
                or "\r" in rule
                or "\n" in rule
                or not rule.startswith(("RRULE:", "RDATE", "EXDATE", "EXRULE:"))
            ):
                raise ValueError("Use bounded RFC5545 recurrence/exception lines.")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        require_time_range(self.start, self.end, recurring=bool(self.recurrence))
        require_recurrence(self.recurrence, self.start)
        if self.event_type != "default" and (
            self.start.date_time is None or self.end.date_time is None
        ):
            raise ValueError("Status events require timed start/end values.")
        if (self.focus_time is not None) != (self.event_type == "focusTime"):
            raise ValueError("Focus-time properties must match the event type.")
        if (self.out_of_office is not None) != (self.event_type == "outOfOffice"):
            raise ValueError("Out-of-office properties must match the event type.")
        return self


class CalendarListInput(CalendarInput):
    page_token: str | None = Field(max_length=8192)
    page_size: int = Field(ge=1, le=100, strict=True)


class CalendarEventListInput(CalendarListInput):
    calendar_id: CalendarId
    time_min: AwareDatetime | None
    time_max: AwareDatetime | None
    query: str | None = Field(max_length=4096)
    expand_recurring: bool = Field(strict=True)
    event_types: tuple[
        Literal[
            "default",
            "outOfOffice",
            "focusTime",
            "workingLocation",
            "birthday",
            "fromGmail",
        ],
        ...,
    ] = Field(max_length=6)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (
            self.time_min is not None
            and self.time_max is not None
            and self.time_max <= self.time_min
        ):
            raise ValueError("Calendar search end must be after start.")
        return self


class CalendarEventGetInput(CalendarInput):
    calendar_id: CalendarId
    event_id: EventId


class CalendarInstancesInput(CalendarEventGetInput):
    page_token: str | None = Field(max_length=8192)
    page_size: int = Field(ge=1, le=100, strict=True)
    time_min: AwareDatetime | None
    time_max: AwareDatetime | None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (
            self.time_min is not None
            and self.time_max is not None
            and self.time_max <= self.time_min
        ):
            raise ValueError("Occurrence search end must be after start.")
        return self


class CalendarFreeBusyInput(CalendarInput):
    calendars: tuple[CalendarId, ...] = Field(min_length=1, max_length=50)
    time_min: AwareDatetime
    time_max: AwareDatetime
    time_zone: str | None

    _timezone = field_validator("time_zone")(require_timezone)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.time_max <= self.time_min:
            raise ValueError("Availability end must be after start.")
        return self


class CalendarSuggestInput(CalendarFreeBusyInput):
    duration_minutes: int = Field(ge=1, le=1440, strict=True)
    maximum_suggestions: int = Field(ge=1, le=20, strict=True)


class CalendarCreateInput(CalendarInput):
    calendar_id: CalendarId
    event: CalendarEventFields
    send_updates: SendUpdates

    @model_validator(mode="after")
    def validate_status_target(self) -> Self:
        if self.event.event_type != "default" and self.calendar_id != "primary":
            raise ValueError(
                "Status events are supported only on the primary calendar."
            )
        return self


@with_config(ConfigDict(extra="forbid", hide_input_in_errors=True))
class CalendarEventPatch(TypedDict, total=False):
    summary: Annotated[str, Field(max_length=4096)]
    description: Annotated[str, Field(max_length=65536)]
    location: Annotated[str, Field(max_length=4096)]
    start: CalendarTime
    end: CalendarTime
    attendees: Annotated[tuple[CalendarAttendee, ...], Field(max_length=200)]
    recurrence: Annotated[tuple[str, ...], Field(max_length=32)]
    focus_time: CalendarFocusTime
    out_of_office: CalendarOutOfOffice
    conference: CalendarConference


class CalendarPatchInput(CalendarEventGetInput):
    changes: CalendarEventPatch
    send_updates: SendUpdates

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        changes = self.changes
        if not changes:
            raise ValueError("Provide at least one event change.")
        if ("start" in changes) != ("end" in changes):
            raise ValueError("Supply both start and end when changing event times.")
        if "recurrence" in changes:
            CalendarEventFields.validate_recurrence(changes["recurrence"])
            if changes["recurrence"] and "start" not in changes:
                raise ValueError("Recurrence changes require explicit start/end times.")
        if "start" in changes and "end" in changes:
            require_time_range(
                changes["start"],
                changes["end"],
                recurring=bool(changes.get("recurrence")),
            )
            require_recurrence(changes.get("recurrence", ()), changes["start"])
        if "focus_time" in changes and "out_of_office" in changes:
            raise ValueError("An event cannot combine different status properties.")
        if (
            "focus_time" in changes or "out_of_office" in changes
        ) and self.calendar_id != "primary":
            raise ValueError("Status event changes require the primary calendar.")
        return self


class CalendarDeleteInput(CalendarEventGetInput):
    send_updates: SendUpdates


class CalendarRsvpInput(CalendarEventGetInput):
    response_status: Literal["accepted", "declined", "tentative"]
    comment: str | None = Field(max_length=8192)
    send_updates: SendUpdates


class CalendarCreateCalendarInput(CalendarInput):
    summary: str = Field(min_length=1, max_length=4096)
    description: str | None = Field(max_length=8192)
    time_zone: str

    _timezone = field_validator("time_zone")(require_timezone)


class CalendarStatusListInput(CalendarEventListInput):
    event_types: tuple[Literal["outOfOffice", "focusTime"], ...] = Field(
        min_length=1, max_length=2
    )


class CalendarStatusCreateInput(CalendarCreateInput):
    @model_validator(mode="after")
    def require_status_type(self) -> Self:
        if self.event.event_type == "default":
            raise ValueError("Select focusTime or outOfOffice for a status event.")
        return self


class CalendarStatusPatchInput(CalendarPatchInput):
    @model_validator(mode="after")
    def require_status_target(self) -> Self:
        if self.calendar_id != "primary":
            raise ValueError("Status events require the primary calendar.")
        if "start" in self.changes and self.changes["start"].date_time is None:
            raise ValueError("Status events require timed start/end values.")
        return self


class CalendarStatusDeleteInput(CalendarDeleteInput):
    @model_validator(mode="after")
    def require_status_target(self) -> Self:
        if self.calendar_id != "primary":
            raise ValueError("Status events require the primary calendar.")
        return self


# Provider responses are partial by contract; omitted fields are not input defaults.
class CalendarProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class CalendarTimeResult(CalendarProviderModel):
    date: Date | None = None
    date_time: AwareDatetime | None = Field(default=None, alias="dateTime")
    time_zone: str | None = Field(default=None, alias="timeZone")


class CalendarAttendeeResult(CalendarProviderModel):
    email: str | None = None
    self_attendee: bool = Field(default=False, alias="self")
    response_status: ResponseStatus | None = Field(default=None, alias="responseStatus")
    display_name: str | None = Field(default=None, alias="displayName")
    optional: bool = False


class CalendarFocusTimeResult(CalendarProviderModel):
    auto_decline_mode: str | None = Field(default=None, alias="autoDeclineMode")
    chat_status: str | None = Field(default=None, alias="chatStatus")
    decline_message: str | None = Field(default=None, alias="declineMessage")


class CalendarOutOfOfficeResult(CalendarProviderModel):
    auto_decline_mode: str | None = Field(default=None, alias="autoDeclineMode")
    decline_message: str | None = Field(default=None, alias="declineMessage")


class CalendarConferenceEntry(CalendarProviderModel):
    entry_point_type: str | None = Field(default=None, alias="entryPointType")
    uri: str | None = None
    label: str | None = None


class CalendarConferenceResult(CalendarProviderModel):
    entry_points: tuple[CalendarConferenceEntry, ...] = Field(
        default=(), alias="entryPoints"
    )


class CalendarEventResult(CalendarProviderModel):
    id: str
    etag: str | None = None
    status: str | None = None
    summary: str | None = None
    description: str | None = None
    location: str | None = None
    html_link: str | None = Field(default=None, alias="htmlLink")
    event_type: str | None = Field(default=None, alias="eventType")
    start: CalendarTimeResult | None = None
    end: CalendarTimeResult | None = None
    recurrence: tuple[str, ...] | None = None
    recurring_event_id: str | None = Field(default=None, alias="recurringEventId")
    original_start_time: CalendarTimeResult | None = Field(
        default=None, alias="originalStartTime"
    )
    attendees: tuple[CalendarAttendeeResult, ...] | None = None
    hangout_link: str | None = Field(default=None, alias="hangoutLink")
    conference: CalendarConferenceResult | None = Field(
        default=None, alias="conferenceData"
    )
    focus_time: CalendarFocusTimeResult | None = Field(
        default=None, alias="focusTimeProperties"
    )
    out_of_office: CalendarOutOfOfficeResult | None = Field(
        default=None, alias="outOfOfficeProperties"
    )


class CalendarEntryResult(CalendarProviderModel):
    id: str
    summary: str | None = None
    description: str | None = None
    time_zone: str | None = Field(default=None, alias="timeZone")
    access_role: str | None = Field(default=None, alias="accessRole")
    primary: bool = False


class CalendarListResult(CalendarProviderModel):
    items: tuple[CalendarEntryResult, ...] = ()
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class CalendarEventListResult(CalendarProviderModel):
    items: tuple[CalendarEventResult, ...] = ()
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    time_zone: str | None = Field(default=None, alias="timeZone")


class CalendarBusyInterval(CalendarProviderModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Provider busy interval end must be after start.")
        return self


class CalendarResourceError(CalendarProviderModel):
    reason: str
    domain: str | None = None


class CalendarBusyResult(CalendarProviderModel):
    busy: tuple[CalendarBusyInterval, ...] = ()
    errors: tuple[CalendarResourceError, ...] = ()


class CalendarFreeBusyResult(CalendarProviderModel):
    calendars: dict[str, CalendarBusyResult]
    time_min: AwareDatetime = Field(alias="timeMin")
    time_max: AwareDatetime = Field(alias="timeMax")

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.time_max <= self.time_min:
            raise ValueError("Provider availability end must be after start.")
        return self


class CalendarSuggestions(CalendarProviderModel):
    suggestions: tuple[CalendarBusyInterval, ...]
