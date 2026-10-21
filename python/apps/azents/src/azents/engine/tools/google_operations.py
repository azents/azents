"""Closed, typed direct Workspace operation projection for the model boundary."""

import asyncio
import dataclasses
from collections.abc import Callable

from azcommon.uuid import uuid7
from pydantic import BaseModel, ValidationError

from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
    FunctionToolSpec,
)
from azents.engine.tools.google_files import GoogleFileBridge
from azents.engine.tools.import_resolver import ImportResolveError
from azents.services.google_workspace import calendar, drive, drive_import, gmail
from azents.services.google_workspace import calendar_models as cm
from azents.services.google_workspace import drive_models as dm
from azents.services.google_workspace import gmail_models as gm
from azents.services.google_workspace.errors import GoogleWorkspacePartialError
from azents.services.google_workspace.execution import GoogleWorkspaceExecution
from azents.services.google_workspace.file_models import (
    GoogleFileInput,
    GooglePreparedFile,
    GoogleWorkspaceOutput,
)
from azents.services.google_workspace.runtime_files import GoogleResolvedInput
from azents.services.google_workspace.transport import (
    GoogleSdkError,
    GoogleSdkLimits,
    GoogleSdkSession,
)


@dataclasses.dataclass(frozen=True)
class GoogleOperationCall:
    execution: GoogleWorkspaceExecution
    files: GoogleFileBridge
    owner: SessionExecutionOwner
    toolkit_id: str
    limits: GoogleSdkLimits
    proxy_url: str | None


@dataclasses.dataclass(frozen=True)
class _Inputs:
    primary_email: str | None
    attachments: tuple[GooglePreparedFile, ...]
    body_file: GooglePreparedFile | None
    prepared: GooglePreparedFile | None
    maximum_bytes: int


@dataclasses.dataclass(frozen=True)
class _Output:
    text: str
    files: tuple[GooglePreparedFile, ...]


def _output[T: BaseModel](value: T | GoogleWorkspaceOutput[T] | None) -> _Output:
    if isinstance(value, GoogleWorkspaceOutput):
        return _Output(value.value.model_dump_json(by_alias=True), value.files)
    return _Output(
        '{"confirmed":true}' if value is None else value.model_dump_json(by_alias=True),
        (),
    )


def _compose(value: BaseModel) -> gm.GmailCompose | None:
    if isinstance(
        value, (gm.GmailSendInput, gm.GmailReplyInput, gm.GmailDraftCreateInput)
    ):
        return value.message
    return None


def _context(value: BaseModel) -> gm.GmailDraftContext | None:
    if isinstance(value, gm.GmailDraftCreateInput):
        return value.context
    if isinstance(value, gm.GmailReplyInput):
        return gm.GmailDraftContext(
            mode="reply",
            source_message_id=value.source_message_id,
            reply_all=value.reply_all,
            quote_original=value.quote_original,
            reuse_source_attachments=value.reuse_source_attachments,
        )
    if isinstance(value, gm.GmailForwardInput):
        return gm.GmailDraftContext(
            mode="forward",
            source_message_id=value.source_message_id,
            reply_all=False,
            quote_original=value.quote_original,
            reuse_source_attachments=value.reuse_source_attachments,
        )
    return None


def _content(value: BaseModel) -> GoogleFileInput | None:
    if isinstance(
        value,
        (dm.DriveCreateFileInput, dm.DriveUpdateContentInput, dm.DriveImportInput),
    ):
        return value.content
    return None


@dataclasses.dataclass(frozen=True)
class GoogleToolDefinition:
    operation: Op
    bind: Callable[[GoogleOperationCall], FunctionTool]


def _definition[T: BaseModel, R: BaseModel](
    operation: Op,
    model: type[T],
    invoke: Callable[
        [GoogleSdkSession, T, _Inputs], R | GoogleWorkspaceOutput[R] | None
    ],
    description: str,
) -> GoogleToolDefinition:
    def bind(call: GoogleOperationCall) -> FunctionTool:
        async def handler(arguments: str) -> FunctionToolResult:
            if len(arguments) > 4 * 1024 * 1024:
                raise FunctionToolError(
                    "Google arguments exceed the bounded input limit. "
                    "No operation was sent."
                )
            try:
                value = model.model_validate_json(arguments)
            except ValidationError:
                # Validation details can contain mail/file content. Do not echo them.
                raise FunctionToolError(
                    "Invalid Google operation arguments. Check the declared fields "
                    "and constraints. No operation was sent."
                ) from None
            try:
                runtime = call.execution.runtime
                message = _compose(value)
                context = _context(value)
                admitted = await runtime.authorize_operation(
                    call.owner,
                    call.toolkit_id,
                    operation,
                    ()
                    if message is None
                    else lambda email: gmail.compose_prerequisites(
                        message, context, email
                    ),
                )

                async def admit() -> None:
                    await runtime.recheck_operation(admitted)

                resolved: list[GoogleResolvedInput] = []

                async def resolve(
                    source: GoogleFileInput | None,
                ) -> GooglePreparedFile | None:
                    if source is None:
                        return None
                    item = await call.files.resolve(source, admit=admit)
                    resolved.append(item)
                    if (
                        sum(entry.file.size for entry in resolved)
                        > call.files.maximum_bytes
                    ):
                        raise GoogleSdkError(
                            "file_input_limit", dispatched=False, status=None
                        )
                    return item.file

                attachments: list[GooglePreparedFile] = []
                if message is not None:
                    for source in message.attachments:
                        file = await resolve(source)
                        assert file is not None
                        attachments.append(file)
                body_file = await resolve(
                    None if message is None else message.body_file
                )
                prepared = await resolve(_content(value))
                inputs = _Inputs(
                    admitted.snapshot.connection.candidate.identity.email,
                    tuple(attachments),
                    body_file,
                    prepared,
                    call.files.maximum_bytes,
                )

                async def revalidate_inputs() -> None:
                    for item in resolved:
                        await item.revalidate()

                result = await call.execution.execute(
                    admitted=admitted,
                    limits=call.limits,
                    proxy_url=call.proxy_url,
                    operation=lambda sdk: _output(invoke(sdk, value, inputs)),
                    revalidate_inputs=revalidate_inputs if resolved else None,
                )
                published = await call.files.publish(
                    result.files,
                    tool_name=operation.value,
                    call_id=uuid7().hex,
                    admit=admit,
                )
                await admit()
                parts: list[dict[str, object]] = [{"type": "text", "text": result.text}]
                parts.extend(
                    {
                        "type": "artifact",
                        "artifact_id": file.artifact_id,
                        "status": file.status,
                        "expires_at": file.expires_at,
                        "uri": file.uri,
                        "name": file.filename,
                        "media_type": file.media_type,
                        "size": file.size,
                    }
                    for file in published
                )
                return FunctionToolResult(output=parts)
            except asyncio.CancelledError:
                raise
            except GoogleWorkspacePartialError as error:
                raise FunctionToolError(
                    "Google operation partially completed. Confirmed steps are "
                    "retained; do not replay them. " + error.partial.model_dump_json(),
                    metadata={
                        "google_error": error.code,
                        "dispatched": error.dispatched,
                    },
                ) from None
            except GoogleSdkError as error:
                raise FunctionToolError(
                    f"Google operation failed ({error.code}). "
                    + (
                        "The operation may have completed; it was not replayed."
                        if error.dispatched
                        else "No Google request was sent."
                    ),
                    metadata={
                        "google_error": error.code,
                        "dispatched": error.dispatched,
                    },
                ) from None
            except GoogleOAuthError as error:
                raise FunctionToolError(
                    f"Current Google authorization is unavailable ({error.code}). "
                    "No request was replayed.",
                ) from None
            except ImportResolveError:
                raise FunctionToolError(
                    "Google file input is unavailable under current Session "
                    "authority. No Google request was sent."
                ) from None

        return FunctionTool(
            spec=FunctionToolSpec(
                name=operation.value,
                description=description
                + " Current scopes and service switches are rechecked before every "
                "SDK request. Use canonical file resources or authorized Runtime "
                "paths. Confirm uncertain writes before retrying.",
                input_schema=model.model_json_schema(),
            ),
            handler=handler,
        )

    return GoogleToolDefinition(operation, bind)


def _simple[T: BaseModel, R: BaseModel](
    operation: Op,
    model: type[T],
    invoke: Callable[[GoogleSdkSession, T], R | GoogleWorkspaceOutput[R] | None],
    description: str,
) -> GoogleToolDefinition:
    return _definition(
        operation, model, lambda sdk, value, inputs: invoke(sdk, value), description
    )


# Each binding fixes the operation, model and public adapter in code. There is no
# model-controlled SDK method, provider URL or arbitrary outgoing body dispatcher.
GOOGLE_TOOLS = (
    _simple(
        Op.GMAIL_SEARCH_MESSAGES,
        gm.GmailSearchInput,
        gmail.search_messages,
        "Search Gmail messages with Google query syntax and bounded pagination.",
    ),
    _simple(
        Op.GMAIL_GET_MESSAGE,
        gm.GmailMessageGetInput,
        gmail.get_message,
        "Read a message with bounded body extraction and optional original "
        "RFC822 publication.",
    ),
    _simple(
        Op.GMAIL_BATCH_GET_MESSAGES,
        gm.GmailBatchGetInput,
        gmail.batch_get_messages,
        "Read multiple messages, retaining explicit partial results on failure.",
    ),
    _simple(
        Op.GMAIL_SEARCH_THREADS,
        gm.GmailSearchInput,
        gmail.search_threads,
        "Search Gmail threads with bounded pagination.",
    ),
    _simple(
        Op.GMAIL_GET_THREAD,
        gm.GmailThreadGetInput,
        gmail.get_thread,
        "Read a Gmail thread and optionally publish original messages.",
    ),
    _definition(
        Op.GMAIL_DOWNLOAD_ATTACHMENT,
        gm.GmailAttachmentInput,
        lambda s, v, i: gmail.download_attachment(s, v, maximum_bytes=i.maximum_bytes),
        "Download an exact message attachment as a canonical file.",
    ),
    _simple(
        Op.GMAIL_LIST_LABELS,
        gm.GmailEmptyInput,
        gmail.list_labels,
        "List Gmail labels.",
    ),
    _simple(
        Op.GMAIL_GET_LABEL, gm.GmailLabelIdInput, gmail.get_label, "Read a Gmail label."
    ),
    _simple(
        Op.GMAIL_CREATE_LABEL,
        gm.GmailLabelCreateInput,
        gmail.create_label,
        "Create a Gmail label.",
    ),
    _simple(
        Op.GMAIL_UPDATE_LABEL,
        gm.GmailLabelPatchInput,
        gmail.update_label,
        "Update supplied Gmail label fields.",
    ),
    _simple(
        Op.GMAIL_DELETE_LABEL,
        gm.GmailLabelIdInput,
        gmail.delete_label,
        "Delete a Gmail label.",
    ),
    _simple(
        Op.GMAIL_LIST_DRAFTS,
        gm.GmailPageInput,
        gmail.list_drafts,
        "List Gmail drafts with bounded pagination.",
    ),
    _simple(
        Op.GMAIL_GET_DRAFT,
        gm.GmailDraftGetInput,
        gmail.get_draft,
        "Read a raw draft and optionally publish its original RFC822 file.",
    ),
    _definition(
        Op.GMAIL_CREATE_DRAFT,
        gm.GmailDraftCreateInput,
        lambda s, v, i: gmail.create_draft(
            s,
            v,
            primary_email=i.primary_email,
            attachments=i.attachments,
            body_file=i.body_file,
        ),
        "Create a draft, optionally using reply/forward context and authorized files.",
    ),
    _definition(
        Op.GMAIL_UPDATE_DRAFT,
        gm.GmailDraftUpdateInput,
        lambda s, v, i: gmail.update_draft(
            s,
            v,
            primary_email=i.primary_email,
            attachments=i.attachments,
            body_file=i.body_file,
        ),
        "Replace a draft's content using typed composition and authorized files.",
    ),
    _simple(
        Op.GMAIL_DELETE_DRAFT,
        gm.GmailDraftIdInput,
        gmail.delete_draft,
        "Delete a Gmail draft.",
    ),
    _simple(
        Op.GMAIL_SEND_DRAFT,
        gm.GmailDraftIdInput,
        gmail.send_draft,
        "Send an existing Gmail draft.",
    ),
    _definition(
        Op.GMAIL_SEND_MESSAGE,
        gm.GmailSendInput,
        lambda s, v, i: gmail.send_message(
            s,
            v,
            primary_email=i.primary_email,
            attachments=i.attachments,
            body_file=i.body_file,
        ),
        "Send a new email. Nonprimary senders require a verified alias and "
        "send-as read scope.",
    ),
    _definition(
        Op.GMAIL_REPLY_MESSAGE,
        gm.GmailReplyInput,
        lambda s, v, i: gmail.reply_message(
            s,
            v,
            primary_email=i.primary_email,
            attachments=i.attachments,
            body_file=i.body_file,
        ),
        "Reply to email, preserving its subject/thread; optional reply-all "
        "and attachment reuse.",
    ),
    _definition(
        Op.GMAIL_FORWARD_MESSAGE,
        gm.GmailForwardInput,
        lambda s, v, i: gmail.forward_message(
            s,
            v,
            primary_email=i.primary_email,
            attachments=i.attachments,
            body_file=i.body_file,
        ),
        "Forward email with optional original quotation and attachment reuse.",
    ),
    _simple(
        Op.GMAIL_MODIFY_MESSAGE,
        gm.GmailModifyMessageInput,
        gmail.modify_message,
        "Add/remove message labels, including mailbox read/star/archive state.",
    ),
    _simple(
        Op.GMAIL_BATCH_MODIFY_MESSAGES,
        gm.GmailBatchModifyInput,
        gmail.batch_modify_messages,
        "Modify message labels in bounded batches with explicit partial outcomes.",
    ),
    _simple(
        Op.GMAIL_MODIFY_THREAD,
        gm.GmailModifyThreadInput,
        gmail.modify_thread,
        "Modify labels on a Gmail thread.",
    ),
    _simple(
        Op.GMAIL_TRASH_MESSAGE,
        gm.GmailMessageIdInput,
        gmail.trash_message,
        "Move a message to trash.",
    ),
    _simple(
        Op.GMAIL_UNTRASH_MESSAGE,
        gm.GmailMessageIdInput,
        gmail.untrash_message,
        "Restore a message from trash.",
    ),
    _simple(
        Op.GMAIL_TRASH_THREAD,
        gm.GmailThreadIdInput,
        gmail.trash_thread,
        "Move a thread to trash.",
    ),
    _simple(
        Op.GMAIL_UNTRASH_THREAD,
        gm.GmailThreadIdInput,
        gmail.untrash_thread,
        "Restore a thread from trash.",
    ),
    _simple(
        Op.GMAIL_LIST_FILTERS,
        gm.GmailEmptyInput,
        gmail.list_filters,
        "List Gmail filters.",
    ),
    _simple(
        Op.GMAIL_GET_FILTER,
        gm.GmailFilterIdInput,
        gmail.get_filter,
        "Read a Gmail filter.",
    ),
    _simple(
        Op.GMAIL_CREATE_FILTER,
        gm.GmailFilterCreateInput,
        gmail.create_filter,
        "Create a persistent Gmail rule for future matching mail. Forwarding "
        "requires a Google-verified target and can continue after service-off "
        "or disconnect.",
    ),
    _simple(
        Op.GMAIL_DELETE_FILTER,
        gm.GmailFilterIdInput,
        gmail.delete_filter,
        "Delete a Gmail filter.",
    ),
    _simple(
        Op.GMAIL_REPLACE_FILTER,
        gm.GmailFilterReplaceInput,
        gmail.replace_filter,
        "Replace a persistent future-mail rule; forwarding needs a verified "
        "target and continues independently of local service-off/disconnect. "
        "Retain confirmed create/delete steps on failure.",
    ),
    _simple(
        Op.GMAIL_APPLY_FILTER,
        gm.GmailFilterApplyInput,
        gmail.apply_filter,
        "Apply label effects only to matching existing mail, with bounded "
        "mutation and explicit partial outcomes. Never forwards historical mail.",
    ),
    _simple(
        Op.GMAIL_PREVIEW_FILTER,
        gm.GmailFilterPreviewInput,
        gmail.preview_filter,
        "Preview existing-mail matches for a saved filter without mutation.",
    ),
    _simple(
        Op.CALENDAR_LIST_CALENDARS,
        cm.CalendarListInput,
        calendar.list_calendars,
        "List accessible calendars.",
    ),
    _simple(
        Op.CALENDAR_LIST_EVENTS,
        cm.CalendarEventListInput,
        calendar.list_events,
        "List calendar events with explicit time bounds, expansion and pagination.",
    ),
    _simple(
        Op.CALENDAR_GET_EVENT,
        cm.CalendarEventGetInput,
        calendar.get_event,
        "Read one calendar event.",
    ),
    _simple(
        Op.CALENDAR_LIST_INSTANCES,
        cm.CalendarInstancesInput,
        calendar.list_instances,
        "List recurring event instances within bounds.",
    ),
    _simple(
        Op.CALENDAR_QUERY_FREEBUSY,
        cm.CalendarFreeBusyInput,
        calendar.query_freebusy,
        "Query availability without fetching event bodies.",
    ),
    _simple(
        Op.CALENDAR_SUGGEST_TIME,
        cm.CalendarSuggestInput,
        calendar.suggest_time,
        "Suggest bounded free time slots from availability.",
    ),
    _simple(
        Op.CALENDAR_CREATE_EVENT,
        cm.CalendarCreateInput,
        calendar.create_event,
        "Create an event with timezone/recurrence, attendees and optional "
        "conference request.",
    ),
    _simple(
        Op.CALENDAR_UPDATE_EVENT,
        cm.CalendarPatchInput,
        calendar.patch_event,
        "Patch supplied event fields; omitted fields are unchanged.",
    ),
    _simple(
        Op.CALENDAR_DELETE_EVENT,
        cm.CalendarDeleteInput,
        calendar.delete_event,
        "Delete an event with explicit notification choice.",
    ),
    _simple(
        Op.CALENDAR_RESPOND_EVENT,
        cm.CalendarRsvpInput,
        calendar.respond_event,
        "RSVP as the connected account after reading the current attendee list.",
    ),
    _simple(
        Op.CALENDAR_LIST_STATUS_EVENTS,
        cm.CalendarStatusListInput,
        calendar.list_status_events,
        "List focus-time and out-of-office events.",
    ),
    _simple(
        Op.CALENDAR_CREATE_STATUS_EVENT,
        cm.CalendarStatusCreateInput,
        calendar.create_status_event,
        "Create a focus-time or out-of-office event.",
    ),
    _simple(
        Op.CALENDAR_UPDATE_STATUS_EVENT,
        cm.CalendarStatusPatchInput,
        calendar.patch_status_event,
        "Patch a current focus-time or out-of-office event.",
    ),
    _simple(
        Op.CALENDAR_DELETE_STATUS_EVENT,
        cm.CalendarStatusDeleteInput,
        calendar.delete_status_event,
        "Delete a verified focus-time or out-of-office event.",
    ),
    _simple(
        Op.CALENDAR_CREATE_CALENDAR,
        cm.CalendarCreateCalendarInput,
        calendar.create_calendar,
        "Create a secondary calendar.",
    ),
    _simple(
        Op.DRIVE_SEARCH_FILES,
        dm.DriveSearchInput,
        drive.search_files,
        "Search Drive files/folders with bounded pagination and query syntax.",
    ),
    _simple(
        Op.DRIVE_GET_METADATA,
        dm.DriveFileIdInput,
        drive.get_metadata,
        "Read Drive metadata, capabilities and shortcut details.",
    ),
    _definition(
        Op.DRIVE_READ_CONTENT,
        dm.DriveReadInput,
        lambda s, v, i: drive.read_content(s, v, maximum_bytes=i.maximum_bytes),
        "Read bounded text from Drive/native exports or PDF/Office; publish "
        "original transfer bytes with truthful extraction status. No OCR "
        "or formula evaluation.",
    ),
    _definition(
        Op.DRIVE_DOWNLOAD_FILE,
        dm.DriveContentInput,
        lambda s, v, i: drive.download_file(s, v, maximum_bytes=i.maximum_bytes),
        "Download original blob bytes as canonical files; native files need export.",
    ),
    _definition(
        Op.DRIVE_EXPORT_FILE,
        dm.DriveExportInput,
        lambda s, v, i: drive.export_file(s, v, maximum_bytes=i.maximum_bytes),
        "Export a native Google file in an explicitly supported format.",
    ),
    _simple(
        Op.DRIVE_GET_LINK,
        dm.DriveFileIdInput,
        drive.get_link,
        "Read a file's Google web link; this does not grant sharing access.",
    ),
    _simple(
        Op.DRIVE_LIST_PERMISSIONS,
        dm.DrivePermissionListInput,
        drive.list_permissions,
        "List a Drive file's sharing permissions.",
    ),
    _simple(
        Op.DRIVE_GET_PERMISSION,
        dm.DrivePermissionIdInput,
        drive.get_permission,
        "Read one Drive sharing permission.",
    ),
    _definition(
        Op.DRIVE_CREATE_FILE,
        dm.DriveCreateFileInput,
        lambda s, v, i: drive.create_file(
            s, v, prepared=i.prepared, maximum_bytes=i.maximum_bytes
        ),
        "Create a Drive blob from inline UTF-8 text or an authorized file.",
    ),
    _simple(
        Op.DRIVE_CREATE_FOLDER,
        dm.DriveCreateFolderInput,
        drive.create_folder,
        "Create a Drive folder.",
    ),
    _simple(
        Op.DRIVE_COPY_FILE,
        dm.DriveCopyInput,
        drive.copy_file,
        "Copy a Drive file with optional parent and name.",
    ),
    _simple(
        Op.DRIVE_UPDATE_METADATA,
        dm.DriveUpdateMetadataInput,
        drive.update_metadata,
        "Update supplied metadata, move parents, or trash/restore a Drive file.",
    ),
    _definition(
        Op.DRIVE_UPDATE_CONTENT,
        dm.DriveUpdateContentInput,
        lambda s, v, i: drive.update_content(
            s, v, prepared=i.prepared, maximum_bytes=i.maximum_bytes
        ),
        "Replace blob content from inline text or an authorized file.",
    ),
    _definition(
        Op.DRIVE_APPEND_TEXT,
        dm.DriveAppendInput,
        lambda s, v, i: drive.append_text(s, v, maximum_bytes=i.maximum_bytes),
        "Append/prepend UTF-8 blob text with a conditional ETag update to "
        "avoid overwriting concurrent edits.",
    ),
    _definition(
        Op.DRIVE_IMPORT_DOCUMENT,
        dm.DriveImportInput,
        lambda s, v, i: drive_import.import_file(
            s, v, target="document", prepared=i.prepared, maximum_bytes=i.maximum_bytes
        ),
        "Import supported text/HTML/Markdown/Office into a native document.",
    ),
    _definition(
        Op.DRIVE_IMPORT_SPREADSHEET,
        dm.DriveImportInput,
        lambda s, v, i: drive_import.import_file(
            s,
            v,
            target="spreadsheet",
            prepared=i.prepared,
            maximum_bytes=i.maximum_bytes,
        ),
        "Import CSV/TSV/Office into a native spreadsheet; fidelity depends "
        "on Google conversion.",
    ),
    _definition(
        Op.DRIVE_IMPORT_PRESENTATION,
        dm.DriveImportInput,
        lambda s, v, i: drive_import.import_file(
            s,
            v,
            target="presentation",
            prepared=i.prepared,
            maximum_bytes=i.maximum_bytes,
        ),
        "Import supported presentation formats into a native presentation; "
        "fidelity depends on Google conversion.",
    ),
    _simple(
        Op.DRIVE_CREATE_PERMISSION,
        dm.DriveCreatePermissionInput,
        drive.create_permissions,
        "Share with users/groups/domain/public recipients; multi-recipient "
        "failures retain confirmed grants.",
    ),
    _simple(
        Op.DRIVE_UPDATE_PERMISSION,
        dm.DriveUpdatePermissionInput,
        drive.update_permission,
        "Update a Drive sharing role or discovery setting.",
    ),
    _simple(
        Op.DRIVE_DELETE_PERMISSION,
        dm.DrivePermissionIdInput,
        drive.delete_permission,
        "Remove a Drive sharing permission.",
    ),
    _simple(
        Op.DRIVE_TRANSFER_OWNERSHIP,
        dm.DriveTransferOwnershipInput,
        drive.transfer_ownership,
        "Transfer ownership to an explicit user with required confirmation.",
    ),
    _simple(
        Op.DRIVE_UPDATE_ACCESS,
        dm.DriveUpdateAccessInput,
        drive.update_access,
        "Update supported file access/copy/security metadata.",
    ),
)
