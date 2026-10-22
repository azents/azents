"""Bounded extraction; original bytes retain independent transfer authority."""

import csv
import dataclasses
import io
import posixpath
import zipfile
from collections.abc import Callable
from typing import Literal
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from pypdf import Configuration, PdfReader, apply_configuration
from pypdf.errors import LimitReachedError, PyPdfError

from azents.services.google_workspace.file_models import GooglePreparedFile

ExtractionStatus = Literal[
    "complete",
    "truncated",
    "unsupported_format",
    "invalid_encoding",
    "encrypted",
    "malformed",
    "input_limit",
    "parser_limit",
]


@dataclasses.dataclass(frozen=True)
class GoogleExtractionLimits:
    maximum_input_bytes: int
    maximum_expanded_bytes: int
    maximum_pages: int
    maximum_cells: int
    maximum_xml_nodes: int
    maximum_characters: int

    def __post_init__(self) -> None:
        if min(dataclasses.astuple(self)) < 1:
            raise ValueError("Extraction limits must be positive.")


@dataclasses.dataclass(frozen=True)
class GoogleExtractedText:
    text: str | None
    status: ExtractionStatus


class _LimitExceeded(ValueError):
    pass


class _EncryptedDocument(ValueError):
    pass


class _MalformedDocument(ValueError):
    pass


def _nonnegative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise _MalformedDocument() from None
    if parsed < 0:
        raise _MalformedDocument()
    return parsed


@dataclasses.dataclass
class _TextBudget:
    maximum: int
    chunks: list[str] = dataclasses.field(default_factory=list, init=False)
    size: int = 0
    truncated: bool = False

    def append(self, text: str) -> None:
        available = max(self.maximum - self.size, 0)
        self.chunks.append(text[:available])
        self.size += min(len(text), available)
        self.truncated = self.truncated or len(text) > available

    def result(self) -> GoogleExtractedText:
        return GoogleExtractedText(
            "".join(self.chunks), "truncated" if self.truncated else "complete"
        )


def _pdf(
    file: GooglePreparedFile,
    limits: GoogleExtractionLimits,
    require_current: Callable[[], None],
) -> GoogleExtractedText:
    config = Configuration(
        maximum_declared_stream_length=limits.maximum_expanded_bytes,
        array_based_stream_maximum_output_length=limits.maximum_expanded_bytes,
        array_maximum_element_count=limits.maximum_xml_nodes,
        dictionary_maximum_element_count=limits.maximum_xml_nodes,
        zlib_maximum_output_length=limits.maximum_expanded_bytes,
        lzw_maximum_output_length=limits.maximum_expanded_bytes,
        run_length_maximum_output_length=limits.maximum_expanded_bytes,
        brotli_maximum_output_length=limits.maximum_expanded_bytes,
        jbig2_maximum_output_length=limits.maximum_expanded_bytes,
        image_maximum_buffer_size=limits.maximum_expanded_bytes,
        stream_decoding_work_maximum_length=limits.maximum_expanded_bytes,
        stream_parsing_work_maximum_count=limits.maximum_xml_nodes,
        page_tree_maximum_entries=limits.maximum_pages * 4,
        page_tree_maximum_depth=20,
        jbig2dec_binary=None,
    )
    budget = _TextBudget(limits.maximum_characters)
    decoded_work = 0
    with apply_configuration(config), io.BytesIO(file.content) as stream:
        reader = PdfReader(stream, strict=True)
        if reader.is_encrypted:
            raise _EncryptedDocument()
        if len(reader.pages) > limits.maximum_pages:
            raise _LimitExceeded()
        for page in reader.pages:
            require_current()
            content = page.get_contents()
            if content is not None:
                decoded_work += len(content.get_data())
                if decoded_work > limits.maximum_expanded_bytes:
                    raise _LimitExceeded()

            def visitor(
                text: str,
                matrix: object,
                text_matrix: object,
                font: object,
                size: float,
            ) -> None:
                require_current()
                budget.append(text)
                if budget.truncated:
                    raise _LimitExceeded()

            try:
                page.extract_text(visitor_text=visitor)
            except _LimitExceeded:
                if budget.truncated:
                    return budget.result()
                raise
            budget.append("\n")
            if budget.truncated:
                return budget.result()
    return budget.result()


def _office(
    file: GooglePreparedFile,
    limits: GoogleExtractionLimits,
    require_current: Callable[[], None],
) -> GoogleExtractedText:
    budget = _TextBudget(limits.maximum_characters)
    with zipfile.ZipFile(io.BytesIO(file.content)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 5000
            or sum(entry.file_size for entry in entries) > limits.maximum_expanded_bytes
        ):
            raise _LimitExceeded()
        names = {entry.filename for entry in entries}
        if len(names) != len(entries) or any(entry.flag_bits & 1 for entry in entries):
            raise _EncryptedDocument()
        if any(name.lower().endswith("vbaproject.bin") for name in names):
            return GoogleExtractedText(None, "unsupported_format")
        consumed = 0
        node_count = 0
        cell_count = 0

        def xml(name: str) -> Element:
            nonlocal consumed, node_count
            require_current()
            info = archive.getinfo(name)
            if info.file_size > limits.maximum_input_bytes:
                raise _LimitExceeded()
            with archive.open(info) as source:
                raw = source.read(
                    min(
                        limits.maximum_input_bytes,
                        limits.maximum_expanded_bytes - consumed,
                    )
                    + 1
                )
            consumed += len(raw)
            if (
                consumed > limits.maximum_expanded_bytes
                or len(raw) > limits.maximum_input_bytes
            ):
                raise _LimitExceeded()
            root: Element = fromstring(
                raw, forbid_dtd=True, forbid_entities=True, forbid_external=True
            )
            for _element in root.iter():
                require_current()
                node_count += 1
                if node_count > limits.maximum_xml_nodes:
                    raise _LimitExceeded()
            return root

        def ordered_parts(
            owner: str,
            relation_file: str,
            element_tag: str,
            expected_type: str,
        ) -> tuple[str, ...]:
            relation_root = xml(relation_file)
            relations = {
                element.attrib["Id"]: element
                for element in relation_root
                if "Id" in element.attrib
            }
            result: list[str] = []
            owner_root = xml(owner)
            relation_id_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            for item in owner_root.iter(element_tag):
                relation = relations.get(item.attrib.get(relation_id_key, ""))
                if relation is None or relation.attrib.get("TargetMode") == "External":
                    raise _MalformedDocument()
                if not relation.attrib.get("Type", "").endswith("/" + expected_type):
                    raise _MalformedDocument()
                target = relation.attrib.get("Target", "")
                name = posixpath.normpath(
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.join(posixpath.dirname(owner), target)
                )
                if name not in names or name.startswith("../") or ":" in name:
                    raise _MalformedDocument()
                result.append(name)
            if len(result) > limits.maximum_pages:
                raise _LimitExceeded()
            return tuple(result)

        if "META-INF/manifest.xml" in names:
            manifest = xml("META-INF/manifest.xml")
            if any(
                element.tag.endswith("}encryption-data") for element in manifest.iter()
            ):
                raise _EncryptedDocument()
        if "word/document.xml" in names:
            root = xml("word/document.xml")
            for paragraph in root.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
            ):
                for element in paragraph.iter():
                    if element.tag.endswith("}t") and element.text:
                        budget.append(element.text)
                    elif element.tag.endswith("}tab"):
                        budget.append("\t")
                    elif element.tag.endswith("}br"):
                        budget.append("\n")
                budget.append("\n")
                if budget.truncated:
                    break
        elif "xl/workbook.xml" in names:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = xml("xl/sharedStrings.xml")
                shared = ["".join(element.itertext()) for element in root]
            sheets = ordered_parts(
                "xl/workbook.xml",
                "xl/_rels/workbook.xml.rels",
                "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet",
                "worksheet",
            )
            ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            for name in sheets:
                root = xml(name)
                budget.append(name + "\n")
                for row in root.iter(ns + "row"):
                    values: list[str] = []
                    for cell in row.findall(ns + "c"):
                        cell_count += 1
                        if cell_count > limits.maximum_cells:
                            raise _LimitExceeded()
                        raw_value = cell.findtext(ns + "v") or ""
                        if cell.attrib.get("t") == "s":
                            index = _nonnegative_integer(raw_value)
                            if index < 0 or index >= len(shared):
                                raise _MalformedDocument()
                            raw_value = shared[index]
                        elif cell.attrib.get("t") == "inlineStr":
                            raw_value = "".join(cell.itertext())
                        # Formula cells use only cached values; never evaluate them.
                        values.append(cell.attrib.get("r", "") + "=" + raw_value)
                    budget.append("\t".join(values) + "\n")
                    if budget.truncated:
                        return budget.result()
        elif "ppt/presentation.xml" in names:
            slides = ordered_parts(
                "ppt/presentation.xml",
                "ppt/_rels/presentation.xml.rels",
                "{http://schemas.openxmlformats.org/presentationml/2006/main}sldId",
                "slide",
            )
            for name in slides:
                root = xml(name)
                budget.append(name + "\n")
                for element in root.iter(
                    "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                ):
                    if element.text:
                        budget.append(element.text + "\n")
                if budget.truncated:
                    return budget.result()
        elif "content.xml" in names and "mimetype" in names:
            root = xml("content.xml")
            table_ns = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
            office_ns = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
            tables = tuple(root.iter(table_ns + "table"))
            if tables:
                if len(tables) > limits.maximum_pages:
                    raise _LimitExceeded()
                for table in tables:
                    for row in table.iter(table_ns + "table-row"):
                        require_current()
                        row_repeats = _nonnegative_integer(
                            row.attrib.get(
                                table_ns + "number-rows-repeated",
                                "1",
                            )
                        )
                        if row_repeats < 1 or row_repeats > limits.maximum_cells:
                            raise _LimitExceeded()
                        values: list[str] = []
                        for cell in row:
                            if cell.tag not in {
                                table_ns + "table-cell",
                                table_ns + "covered-table-cell",
                            }:
                                continue
                            repeats = _nonnegative_integer(
                                cell.attrib.get(
                                    table_ns + "number-columns-repeated",
                                    "1",
                                )
                            )
                            if repeats < 1:
                                raise _MalformedDocument()
                            cell_count += repeats * row_repeats
                            if cell_count > limits.maximum_cells:
                                raise _LimitExceeded()
                            text = " ".join(
                                "".join(element.itertext())
                                for element in cell.iter()
                                if element.tag.endswith("}p")
                            )
                            if not text:
                                text = (
                                    cell.attrib.get(office_ns + "string-value")
                                    or cell.attrib.get(office_ns + "value")
                                    or cell.attrib.get(office_ns + "date-value")
                                    or cell.attrib.get(office_ns + "boolean-value")
                                    or ""
                                )
                            values.extend([text] * repeats)
                        for _ in range(row_repeats):
                            budget.append("\t".join(values) + "\n")
                            if budget.truncated:
                                return budget.result()
                return budget.result()
            for element in root.iter():
                if element.tag.endswith(("}p", "}h")):
                    budget.append("".join(element.itertext()) + "\n")
                if budget.truncated:
                    return budget.result()
        else:
            return GoogleExtractedText(None, "unsupported_format")
    return budget.result()


def extract_text(
    file: GooglePreparedFile,
    limits: GoogleExtractionLimits,
    require_current: Callable[[], None],
) -> GoogleExtractedText:
    require_current()
    if file.size > limits.maximum_input_bytes:
        return GoogleExtractedText(None, "input_limit")
    try:
        if file.media_type == "application/pdf":
            return _pdf(file, limits, require_current)
        if file.media_type in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.oasis.opendocument.text",
            "application/vnd.oasis.opendocument.spreadsheet",
            "application/vnd.oasis.opendocument.presentation",
        }:
            return _office(file, limits, require_current)
        if file.media_type.startswith("text/") or file.media_type in {
            "application/json",
            "application/xml",
        }:
            text = file.content.decode("utf-8-sig")
            if file.media_type in {"text/csv", "text/tab-separated-values"}:
                cell_count = 0
                for row in csv.reader(
                    io.StringIO(text),
                    delimiter="\t"
                    if file.media_type == "text/tab-separated-values"
                    else ",",
                ):
                    require_current()
                    cell_count += len(row)
                    if cell_count > limits.maximum_cells:
                        raise _LimitExceeded()
            return GoogleExtractedText(
                text[: limits.maximum_characters],
                "truncated" if len(text) > limits.maximum_characters else "complete",
            )
        return GoogleExtractedText(None, "unsupported_format")
    except _EncryptedDocument:
        return GoogleExtractedText(None, "encrypted")
    except _LimitExceeded, LimitReachedError:
        return GoogleExtractedText(None, "parser_limit")
    except UnicodeDecodeError:
        return GoogleExtractedText(None, "invalid_encoding")
    except (
        PyPdfError,
        DefusedXmlException,
        ParseError,
        zipfile.BadZipFile,
        csv.Error,
        _MalformedDocument,
        KeyError,
        IndexError,
        OverflowError,
        RecursionError,
    ):
        return GoogleExtractedText(None, "malformed")
