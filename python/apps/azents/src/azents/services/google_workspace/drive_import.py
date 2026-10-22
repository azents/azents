"""Supported Drive conversion inputs; no lossless native editing or OCR claim."""

import io
import zipfile
from typing import TYPE_CHECKING, Literal
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from googleapiclient.http import MediaIoBaseUpload
from markdown_it import MarkdownIt

from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES
from azents.services.google_workspace import drive_models as m
from azents.services.google_workspace.drive import DRIVE_METADATA_FIELDS
from azents.services.google_workspace.file_models import GooglePreparedFile
from azents.services.google_workspace.transport import GoogleSdkError, GoogleSdkSession

if TYPE_CHECKING:
    from googleapiclient._apis.drive.v3.schemas import File

_SOURCES = {
    "text": "text/plain",
    "html": "text/html",
    "markdown": "text/markdown",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "rtf": "application/rtf",
}
_ALLOWED_SOURCES = {
    "document": {"text", "html", "markdown", "docx", "odt", "rtf"},
    "spreadsheet": {"text", "html", "csv", "tsv", "xlsx", "ods"},
    "presentation": {"pptx", "odp"},
}
_EXPECTED_ENTRIES = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}


def validate_office_archive(content: bytes, source_format: str) -> None:
    """Bound the original import format before delegating conversion to Google."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 5000
                or sum(entry.file_size for entry in entries) > 64 * 1024 * 1024
            ):
                raise GoogleSdkError(
                    "office_expansion_limit", dispatched=False, status=None
                )
            names = {entry.filename for entry in entries}
            if len(names) != len(entries) or any(
                entry.flag_bits & 1
                or entry.file_size > 16 * 1024 * 1024
                or ".." in entry.filename.split("/")
                or entry.filename.startswith(("/", "\\"))
                for entry in entries
            ):
                raise GoogleSdkError(
                    "unsafe_office_archive", dispatched=False, status=None
                )
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise GoogleSdkError(
                    "unsupported_macro_format", dispatched=False, status=None
                )
            expected = _EXPECTED_ENTRIES.get(source_format)
            if expected is not None and (
                expected not in names or "[Content_Types].xml" not in names
            ):
                raise GoogleSdkError(
                    "invalid_office_format", dispatched=False, status=None
                )
            if source_format in {"odt", "ods", "odp"}:
                if "mimetype" not in names or archive.read("mimetype") != _SOURCES[
                    source_format
                ].encode("ascii"):
                    raise GoogleSdkError(
                        "invalid_office_format", dispatched=False, status=None
                    )
                if "META-INF/manifest.xml" in names:
                    manifest: Element = fromstring(
                        archive.read("META-INF/manifest.xml"),
                        forbid_dtd=True,
                        forbid_entities=True,
                        forbid_external=True,
                    )
                    if any(
                        element.tag.endswith("}encryption-data")
                        for element in manifest.iter()
                    ):
                        raise GoogleSdkError(
                            "encrypted_office_import", dispatched=False, status=None
                        )
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        DefusedXmlException,
        ParseError,
    ):
        raise GoogleSdkError(
            "invalid_office_archive", dispatched=False, status=None
        ) from None


def import_file(
    session: GoogleSdkSession,
    value: m.DriveImportInput,
    *,
    target: Literal["document", "spreadsheet", "presentation"],
    prepared: GooglePreparedFile | None,
    maximum_bytes: int,
) -> m.DriveMetadata:
    if value.source_format not in _ALLOWED_SOURCES[target]:
        raise GoogleSdkError(
            "unsupported_import_conversion", dispatched=False, status=None
        )
    if (value.content is None) != (prepared is None):
        raise ValueError("Resolve and authorize the exact Drive import source first.")
    content = (
        prepared.content if prepared is not None else (value.text or "").encode("utf-8")
    )
    maximum = min(maximum_bytes, GENERAL_FILE_MAXIMUM_BYTES)
    if maximum <= 0 or len(content) > maximum:
        raise GoogleSdkError("file_upload_limit", dispatched=False, status=None)
    media_type = _SOURCES[value.source_format]
    if value.source_format in {"docx", "xlsx", "pptx", "odt", "ods", "odp"}:
        validate_office_archive(content, value.source_format)
    elif value.source_format == "rtf":
        if not content.lstrip().startswith(b"{\\rtf"):
            raise GoogleSdkError("invalid_rtf_source", dispatched=False, status=None)
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise GoogleSdkError(
                "import_requires_utf8", dispatched=False, status=None
            ) from None
        if value.source_format == "markdown":
            # Rendering performs no network fetch or execution of embedded content.
            content = (
                MarkdownIt("commonmark", {"html": True}).render(text).encode("utf-8")
            )
            media_type = "text/html"
            if len(content) > maximum:
                raise GoogleSdkError(
                    "conversion_output_limit", dispatched=False, status=None
                )
    body: File = {
        "name": value.name,
        "mimeType": "application/vnd.google-apps." + target,
    }
    if value.parent_id is not None:
        body["parents"] = [value.parent_id]
    with io.BytesIO(content) as source:
        upload = MediaIoBaseUpload(
            source, mimetype=media_type, chunksize=1024 * 1024, resumable=True
        )
        return session.decode(
            m.DriveMetadata,
            session.drive.files().create(
                body=body,
                media_body=upload,
                supportsAllDrives=True,
                fields=DRIVE_METADATA_FIELDS,
            ),
        )
