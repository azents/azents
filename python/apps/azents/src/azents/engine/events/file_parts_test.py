"""Event FilePart lowering tests."""

from azents.engine.events.file_parts import (
    FilePartLoweringCapabilities,
    ModelFileLoweringContent,
    RequestLocalModelFileResolver,
    lower_file_output_part,
)
from azents.engine.events.types import FileOutputPart


def test_image_file_part_does_not_use_generic_file_byte_budget() -> None:
    """Image FileParts are not blocked by the 1MB generic input_file budget."""
    part = FileOutputPart(
        model_file_id="mf_image",
        media_type="image/jpeg",
        name="large.jpg",
        size=2_969_090,
        kind="image",
    )
    resolver = RequestLocalModelFileResolver()
    resolver.put(
        model_file_id="mf_image",
        content=ModelFileLoweringContent(
            data_url="data:image/jpeg;base64,abcd",
        ),
    )

    lowered = lower_file_output_part(
        part,
        capabilities=FilePartLoweringCapabilities(
            supports_image_input=True,
            max_file_bytes=1_000_000,
        ),
        resolver=resolver,
    )

    assert lowered == {
        "type": "input_image",
        "detail": "auto",
        "image_url": "data:image/jpeg;base64,abcd",
    }


def test_non_image_file_part_still_uses_generic_file_byte_budget() -> None:
    """Non-image FileParts keep the existing generic input_file budget."""
    part = FileOutputPart(
        model_file_id="mf_pdf",
        media_type="application/pdf",
        name="large.pdf",
        size=2_000_000,
        kind="document",
    )
    resolver = RequestLocalModelFileResolver()
    resolver.put(
        model_file_id="mf_pdf",
        content=ModelFileLoweringContent(
            data_url="data:application/pdf;base64,abcd",
        ),
    )

    lowered = lower_file_output_part(
        part,
        capabilities=FilePartLoweringCapabilities(
            supports_file_input=True,
            supports_pdf_input=True,
            max_file_bytes=1_000_000,
        ),
        resolver=resolver,
    )

    assert lowered["type"] == "input_text"
    assert "file exceeds model file input budget" in str(lowered["text"])
