"""Closed Gmail operation inputs and typed provider/Agent projections."""

from email.errors import HeaderParseError
from email.headerregistry import Address
from typing import Annotated, Literal, Self, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
    with_config,
)

from azents.services.google_workspace.file_models import GoogleFileInput

GmailId = Annotated[
    str, StringConstraints(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
]
GmailPartId = Annotated[
    str, StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.-]+$")
]


class GmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GmailEmptyInput(GmailInput):
    """Empty input for account-bound label and filter listing."""


class GmailMailbox(GmailInput):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\r\n\x00]+$")
    display_name: str | None = Field(max_length=256, pattern=r"^[^\r\n\x00]*$")

    @field_validator("email")
    @classmethod
    def validate_address(cls, value: str) -> str:
        try:
            parsed = Address(addr_spec=value)
        except ValueError, HeaderParseError:
            raise ValueError(
                "Use one valid mailbox address without headers or display text."
            ) from None
        if value != value.strip() or not parsed.username or not parsed.domain:
            raise ValueError("Mailbox address must have a local part and domain.")
        try:
            domain = parsed.domain.encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("Mailbox domain must be a valid IDNA domain.") from None
        return Address(username=parsed.username, domain=domain).addr_spec


class GmailCompose(GmailInput):
    sender: GmailMailbox | None = Field(
        description=(
            "Null uses the connected account. A nonprimary sender needs actual "
            "send-as-read permission and a Google-verified alias; it never selects "
            "another stored credential."
        )
    )
    to: tuple[GmailMailbox, ...] = Field(max_length=500)
    cc: tuple[GmailMailbox, ...] = Field(max_length=500)
    bcc: tuple[GmailMailbox, ...] = Field(max_length=500)
    reply_to: tuple[GmailMailbox, ...] = Field(max_length=50)
    subject: str | None = Field(
        max_length=998,
        pattern=r"^[^\r\n\x00]*$",
        description=(
            "Null derives the subject for a reply/forward. Replies must retain "
            "the normalized original subject to preserve their thread."
        ),
    )
    text: str | None = Field(max_length=1_000_000)
    html: str | None = Field(max_length=1_000_000)
    body_file: GoogleFileInput | None
    body_file_format: Literal["plain", "html"] | None
    attachments: tuple[GoogleFileInput, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def validate_message(self) -> Self:
        if len(self.to) + len(self.cc) + len(self.bcc) > 500:
            raise ValueError("Gmail message has too many recipients.")
        if (self.body_file is None) != (self.body_file_format is None):
            raise ValueError(
                "A body file and its UTF-8 text/HTML format must be supplied together."
            )
        if self.body_file is not None and (
            self.text is not None or self.html is not None
        ):
            raise ValueError("Choose an inline body or one body file, not both.")
        return self


class GmailSendInput(GmailInput):
    message: GmailCompose

    @model_validator(mode="after")
    def require_recipients(self) -> Self:
        if not self.message.to and not self.message.cc and not self.message.bcc:
            raise ValueError("A new message requires at least one recipient.")
        return self


class GmailReplyInput(GmailInput):
    message: GmailCompose
    source_message_id: GmailId
    reply_all: bool = Field(strict=True)
    quote_original: bool = Field(strict=True)
    reuse_source_attachments: bool = Field(strict=True)


class GmailForwardInput(GmailSendInput):
    source_message_id: GmailId
    quote_original: bool = Field(strict=True)
    reuse_source_attachments: bool = Field(strict=True)


class GmailDraftContext(GmailInput):
    mode: Literal["reply", "forward"]
    source_message_id: GmailId
    reply_all: bool = Field(strict=True)
    quote_original: bool = Field(strict=True)
    reuse_source_attachments: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode == "forward" and self.reply_all:
            raise ValueError("Reply-all is not a forwarding option.")
        return self


class GmailDraftCreateInput(GmailInput):
    message: GmailCompose
    context: GmailDraftContext | None


class GmailDraftUpdateInput(GmailDraftCreateInput):
    draft_id: GmailId


class GmailMessageIdInput(GmailInput):
    message_id: GmailId


class GmailMessageGetInput(GmailMessageIdInput):
    body_character_limit: int = Field(ge=1, le=65536, strict=True)


class GmailBatchGetInput(GmailInput):
    message_ids: tuple[GmailId, ...] = Field(min_length=1, max_length=50)
    body_character_limit: int = Field(ge=1, le=65536, strict=True)


class GmailThreadIdInput(GmailInput):
    thread_id: GmailId


class GmailThreadGetInput(GmailThreadIdInput):
    body_character_limit: int = Field(ge=1, le=65536, strict=True)
    maximum_messages: int = Field(ge=1, le=100, strict=True)


class GmailDraftIdInput(GmailInput):
    draft_id: GmailId


class GmailDraftGetInput(GmailDraftIdInput):
    body_character_limit: int = Field(ge=1, le=65536, strict=True)


class GmailPageInput(GmailInput):
    query: str | None = Field(max_length=4096)
    page_token: str | None = Field(max_length=8192)
    page_size: int = Field(ge=1, le=500, strict=True)
    include_spam_trash: bool = Field(strict=True)


class GmailSearchInput(GmailPageInput):
    label_ids: tuple[GmailId, ...] = Field(max_length=100)


class GmailAttachmentInput(GmailMessageIdInput):
    attachment_id: GmailId | None
    part_id: GmailPartId | None

    @model_validator(mode="after")
    def require_exact_part(self) -> Self:
        if (self.attachment_id is None) == (self.part_id is None):
            raise ValueError("Identify exactly one attachment ID or message part ID.")
        return self


class GmailLabelIdInput(GmailInput):
    label_id: GmailId


class GmailLabelColor(GmailInput):
    background_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    text_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class GmailLabelCreateInput(GmailInput):
    name: str = Field(min_length=1, max_length=225)
    label_list_visibility: Literal["labelShow", "labelShowIfUnread", "labelHide"]
    message_list_visibility: Literal["show", "hide"]
    color: GmailLabelColor | None


@with_config(ConfigDict(extra="forbid", hide_input_in_errors=True))
class GmailLabelPatch(TypedDict, total=False):
    name: Annotated[str, Field(min_length=1, max_length=225)]
    label_list_visibility: Literal["labelShow", "labelShowIfUnread", "labelHide"]
    message_list_visibility: Literal["show", "hide"]
    color: GmailLabelColor


class GmailLabelPatchInput(GmailLabelIdInput):
    changes: GmailLabelPatch

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.changes:
            raise ValueError("Provide at least one label change.")
        return self


def require_label_effects(add: tuple[str, ...], remove: tuple[str, ...]) -> None:
    if set(add) & set(remove):
        raise ValueError("A label cannot be added and removed in the same request.")
    if {"SENT", "DRAFT", "CHAT"} & (set(add) | set(remove)):
        raise ValueError("Google controls sent, draft and chat membership.")


class GmailLabelEffects(GmailInput):
    add_label_ids: tuple[GmailId, ...] = Field(max_length=100)
    remove_label_ids: tuple[GmailId, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_effects(self) -> Self:
        require_label_effects(self.add_label_ids, self.remove_label_ids)
        if not self.add_label_ids and not self.remove_label_ids:
            raise ValueError("Provide at least one label effect.")
        return self


class GmailModifyMessageInput(GmailLabelEffects):
    message_id: GmailId


class GmailModifyThreadInput(GmailLabelEffects):
    thread_id: GmailId


class GmailBatchModifyInput(GmailLabelEffects):
    message_ids: tuple[GmailId, ...] = Field(min_length=1, max_length=1000)


class GmailFilterCriteria(GmailInput):
    sender: str | None = Field(max_length=1024)
    recipient: str | None = Field(max_length=1024)
    subject: str | None = Field(max_length=1024)
    query: str | None = Field(max_length=4096)
    negated_query: str | None = Field(max_length=4096)
    has_attachment: bool | None = Field(strict=True)
    exclude_chats: bool | None = Field(strict=True)
    size: int | None = Field(ge=0, strict=True)
    size_comparison: Literal["smaller", "larger"] | None

    @model_validator(mode="after")
    def validate_size(self) -> Self:
        if (self.size is None) != (self.size_comparison is None):
            raise ValueError("Filter size and comparison must be supplied together.")
        return self


class GmailFilterAction(GmailInput):
    add_label_ids: tuple[GmailId, ...] = Field(max_length=100)
    remove_label_ids: tuple[GmailId, ...] = Field(max_length=100)
    forward: str | None = Field(
        max_length=320,
        description=(
            "Forward future matching mail automatically to this Google-verified "
            "target. This persistent Gmail rule can continue after the local "
            "service is disabled or disconnected; delete the filter to stop it. "
            "Applying a filter to existing mail changes labels only and does not "
            "forward historical messages."
        ),
    )

    @field_validator("forward")
    @classmethod
    def validate_forward(cls, value: str | None) -> str | None:
        return (
            None
            if value is None
            else GmailMailbox(email=value, display_name=None).email
        )

    @model_validator(mode="after")
    def validate_effects(self) -> Self:
        require_label_effects(self.add_label_ids, self.remove_label_ids)
        if (
            not self.add_label_ids
            and not self.remove_label_ids
            and self.forward is None
        ):
            raise ValueError("Provide at least one filter action.")
        return self


class GmailFilterCreateInput(GmailInput):
    criteria: GmailFilterCriteria
    action: GmailFilterAction


class GmailFilterIdInput(GmailInput):
    filter_id: GmailId


class GmailFilterReplaceInput(GmailFilterCreateInput):
    filter_id: GmailId


class GmailFilterPreviewInput(GmailFilterIdInput):
    maximum_messages: int = Field(ge=1, le=1000, strict=True)
    page_token: str | None = Field(max_length=8192)
    include_spam_trash: bool = Field(strict=True)


class GmailFilterApplyInput(GmailFilterPreviewInput):
    """Actual existing-mail label changes, separate from read-only preview."""


# Provider DTO defaults describe documented omitted fields, not caller intent.
class GmailProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class GmailHeader(GmailProviderModel):
    name: str = Field(max_length=1024)
    value: str = Field(max_length=65536, repr=False)


class GmailBody(GmailProviderModel):
    attachment_id: GmailId | None = Field(default=None, alias="attachmentId")
    data: str | None = Field(default=None, repr=False)
    size: int | None = Field(default=None, ge=0, strict=True)


class GmailPart(GmailProviderModel):
    part_id: str | None = Field(default=None, alias="partId", max_length=256)
    mime_type: str = Field(
        default="application/octet-stream", alias="mimeType", max_length=255
    )
    filename: str = Field(default="", max_length=4096)
    headers: tuple[GmailHeader, ...] = Field(default=(), max_length=1000)
    body: GmailBody | None = None
    parts: tuple["GmailPart", ...] = Field(default=(), max_length=1000)


class GmailMessageSummary(GmailProviderModel):
    id: GmailId
    thread_id: GmailId | None = Field(default=None, alias="threadId")
    label_ids: tuple[GmailId, ...] = Field(
        default=(), alias="labelIds", max_length=1000
    )
    snippet: str | None = Field(default=None, max_length=8192)
    size_estimate: int | None = Field(default=None, alias="sizeEstimate", ge=0)


class GmailMessageEnvelope(GmailMessageSummary):
    payload: GmailPart | None = None
    raw: str | None = Field(default=None, repr=False)


class GmailThreadEnvelope(GmailProviderModel):
    id: GmailId
    messages: tuple[GmailMessageEnvelope, ...] = Field(default=(), max_length=1000)


class GmailDraftEnvelope(GmailProviderModel):
    id: GmailId
    message: GmailMessageEnvelope


class GmailDraftSummary(GmailProviderModel):
    id: GmailId
    message: GmailMessageSummary


class GmailMessageListResult(GmailProviderModel):
    messages: tuple[GmailMessageSummary, ...] = Field(default=(), max_length=500)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    result_size_estimate: int | None = Field(default=None, alias="resultSizeEstimate")


class GmailThreadListResult(GmailProviderModel):
    threads: tuple[GmailMessageSummary, ...] = Field(default=(), max_length=500)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    result_size_estimate: int | None = Field(default=None, alias="resultSizeEstimate")


class GmailDraftListResult(GmailProviderModel):
    drafts: tuple[GmailDraftSummary, ...] = Field(default=(), max_length=500)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    result_size_estimate: int | None = Field(default=None, alias="resultSizeEstimate")


class GmailAttachmentInfo(GmailProviderModel):
    part_id: str | None
    attachment_id: str | None
    filename: str
    media_type: str
    size: int | None


class GmailTextPart(GmailProviderModel):
    media_type: str
    text: str | None
    status: Literal["complete", "truncated", "unsupported_charset", "invalid_encoding"]


class GmailMessageResult(GmailMessageSummary):
    headers: tuple[GmailHeader, ...]
    body_parts: tuple[GmailTextPart, ...]
    attachments: tuple[GmailAttachmentInfo, ...]


class GmailThreadResult(GmailProviderModel):
    id: str
    messages: tuple[GmailMessageResult, ...]
    truncated: bool
    remaining_message_ids: tuple[str, ...]


class GmailDraftResult(GmailProviderModel):
    id: str
    message: GmailMessageResult


class GmailBatchMessageResult(GmailProviderModel):
    messages: tuple[GmailMessageResult, ...]


class GmailMutationResult(GmailProviderModel):
    confirmed_ids: tuple[str, ...]


class GmailThreadMutationResult(GmailProviderModel):
    id: GmailId
    messages: tuple[GmailMessageSummary, ...] = ()


class GmailLabelResult(GmailProviderModel):
    id: GmailId
    name: str | None = None
    type: Literal["system", "user"] | None = None
    label_list_visibility: str | None = Field(default=None, alias="labelListVisibility")
    message_list_visibility: str | None = Field(
        default=None, alias="messageListVisibility"
    )
    messages_total: int | None = Field(default=None, alias="messagesTotal")
    messages_unread: int | None = Field(default=None, alias="messagesUnread")


class GmailLabelListResult(GmailProviderModel):
    labels: tuple[GmailLabelResult, ...] = ()


class GmailProviderFilterCriteria(GmailProviderModel):
    # Unknown criteria must not be dropped before applying a filter to old mail.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    sender: str | None = Field(default=None, alias="from", max_length=1024)
    recipient: str | None = Field(default=None, alias="to", max_length=1024)
    subject: str | None = Field(default=None, max_length=1024)
    query: str | None = Field(default=None, max_length=4096)
    negated_query: str | None = Field(
        default=None, alias="negatedQuery", max_length=4096
    )
    has_attachment: bool = Field(default=False, alias="hasAttachment", strict=True)
    exclude_chats: bool = Field(default=False, alias="excludeChats", strict=True)
    size: int | None = Field(default=None, ge=0, strict=True)
    size_comparison: Literal["unspecified", "smaller", "larger"] | None = Field(
        default=None, alias="sizeComparison"
    )


class GmailProviderFilterAction(GmailProviderModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    add_label_ids: tuple[GmailId, ...] = Field(
        default=(), alias="addLabelIds", max_length=100
    )
    remove_label_ids: tuple[GmailId, ...] = Field(
        default=(), alias="removeLabelIds", max_length=100
    )
    forward: str | None = Field(default=None, max_length=320)


class GmailFilterResult(GmailProviderModel):
    id: GmailId
    criteria: GmailProviderFilterCriteria
    action: GmailProviderFilterAction


class GmailFilterReceipt(GmailProviderModel):
    id: GmailId
    criteria: GmailProviderFilterCriteria | None = None
    action: GmailProviderFilterAction | None = None


class GmailFilterListResult(GmailProviderModel):
    filter: tuple[GmailFilterResult, ...] = Field(default=(), max_length=1000)


class GmailFilterReplaceResult(GmailProviderModel):
    created_filter_id: str
    deleted_filter_id: str


class GmailFilterApplyResult(GmailProviderModel):
    matched_message_ids: tuple[str, ...]
    confirmed_message_ids: tuple[str, ...]
    next_page_token: str | None
    dry_run: bool
    forwarding_applied: Literal[False]


class GmailSendAsResult(GmailProviderModel):
    send_as_email: str = Field(alias="sendAsEmail")
    verification_status: str | None = Field(default=None, alias="verificationStatus")
