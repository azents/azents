"""read_text tool tests."""

import json

import pytest

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.read_text import _read_character_range, make_read_text_tool
from azents.engine.tools.testing import FakeSharedStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create read_text tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    tool = make_read_text_tool(
        session_storage=storage,
        agent_id="",
    )
    return tool, storage


# ---------------------------------------------------------------------------
# TestReadTextFromSessionData
# ---------------------------------------------------------------------------


class TestReadTextFromSessionData:
    """Text file read tests from session data."""

    async def test_read_full_file(self) -> None:
        """Read entire short text file."""
        # Given: text file in session data
        content = "Hello, world!"
        tool, _ = _make_tool(files={"/workspace/agent/note.txt": content.encode()})

        # When: call read_text
        result = await tool.handler(json.dumps({"path": "/workspace/agent/note.txt"}))

        # Then: full content is included
        assert isinstance(result, str)
        assert "Hello, world!" in result
        assert "characters 0-13" in result

    async def test_read_with_offset(self) -> None:
        """Read from the middle with offset."""
        # Given: long text
        content = "A" * 100
        tool, _ = _make_tool(files={"/workspace/agent/data.txt": content.encode()})

        # When: call with offset=50
        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/data.txt", "offset": 50})
        )

        # Then: read from 50th character
        assert isinstance(result, str)
        assert "characters 50-100" in result

    async def test_read_with_limit(self) -> None:
        """Read only beginning with limit."""
        # Given: long text
        content = "B" * 20_000
        tool, _ = _make_tool(files={"/workspace/agent/big.txt": content.encode()})

        # When: call with limit=5000
        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/big.txt", "limit": 5000})
        )

        # Then: return only 5000 chars and include guidance to read more
        assert isinstance(result, str)
        assert "characters 0-5000" in result
        assert "Use offset=5000 to read more" in result

    async def test_read_with_offset_and_limit(self) -> None:
        """offset + limit combination test."""
        # Given: text
        content = "C" * 500
        tool, _ = _make_tool(files={"/workspace/agent/mid.txt": content.encode()})

        # When: offset=100, limit=200
        result = await tool.handler(
            json.dumps(
                {"path": "/workspace/agent/mid.txt", "offset": 100, "limit": 200}
            )
        )

        # Then: return range 100-300
        assert isinstance(result, str)
        assert "characters 100-300" in result

    async def test_offset_beyond_file_length(self) -> None:
        """Return empty content when offset exceeds file length."""
        # Given: short text
        tool, _ = _make_tool(files={"/workspace/agent/short.txt": b"hi"})

        # When: offset=100
        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/short.txt", "offset": 100})
        )

        # Then: empty content, range display
        assert isinstance(result, str)
        assert "characters 100-100" in result

    async def test_no_more_hint_when_fully_read(self) -> None:
        """No 'Use offset' guidance when entire file is read."""
        # Given: short text
        tool, _ = _make_tool(files={"/workspace/agent/small.txt": b"abc"})

        # When: read entire file
        result = await tool.handler(json.dumps({"path": "/workspace/agent/small.txt"}))

        # Then: no guidance to read more
        assert isinstance(result, str)
        assert "Use offset" not in result

    async def test_read_uses_explicit_encoding(self) -> None:
        """Decode a text file with the caller-selected encoding."""
        tool, _ = _make_tool(
            files={"/workspace/agent/latin.txt": "café".encode("latin-1")}
        )

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/latin.txt",
                    "encoding": "latin-1",
                }
            )
        )

        assert isinstance(result, str)
        assert "café" in result

    @pytest.mark.parametrize(
        ("content", "offset", "limit", "expected"),
        [
            ("ABC", 1, 1, "B"),
            ("가나다", 1, 1, "나"),
            ("日本語", 1, 1, "本"),
            ("😀😃😄", 1, 1, "😃"),
            ("A가日😀Z", 1, 3, "가日😀"),
        ],
    )
    async def test_read_uses_character_offsets_for_mixed_width_text(
        self,
        content: str,
        offset: int,
        limit: int,
        expected: str,
    ) -> None:
        """Offsets and limits count decoded characters for mixed-width text."""
        tool, _ = _make_tool(
            files={"/workspace/agent/mixed.txt": content.encode("utf-8")}
        )

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/mixed.txt",
                    "offset": offset,
                    "limit": limit,
                }
            )
        )

        assert isinstance(result, str)
        assert f"characters {offset}-{offset + len(expected)}" in result
        assert f"\n\n{expected}\n" in result

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [
            (0, "A"),
            (1, "가"),
            (2, "B"),
        ],
    )
    async def test_read_offsets_immediately_around_multibyte_character(
        self,
        offset: int,
        expected: str,
    ) -> None:
        """Offsets before, at, and after a multibyte character remain valid."""
        tool, _ = _make_tool(
            files={"/workspace/agent/boundary.txt": "A가B".encode("utf-8")}
        )

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/boundary.txt",
                    "offset": offset,
                    "limit": 1,
                }
            )
        )

        assert isinstance(result, str)
        assert f"\n\n{expected}" in result

    async def test_read_decodes_character_split_across_storage_chunks(self) -> None:
        """A storage chunk boundary cannot create a UTF-8 decode failure."""
        content = ("A" * (64 * 1024 - 1)) + "가B"
        tool, storage = _make_tool(
            files={"/workspace/agent/chunked.txt": content.encode("utf-8")}
        )

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/chunked.txt",
                    "offset": 64 * 1024 - 1,
                    "limit": 2,
                }
            )
        )

        assert isinstance(result, str)
        assert "\n\n가B" in result
        assert len(storage.read_range_calls) == 2
        assert all(
            max_bytes == 64 * 1024 for _, _, max_bytes in storage.read_range_calls
        )


# ---------------------------------------------------------------------------
# TestReadTextErrors
# ---------------------------------------------------------------------------


class TestReadTextErrors:
    """Error case tests."""

    @pytest.mark.parametrize(
        ("offset", "limit"),
        [
            (-1, 1),
            (0, 0),
        ],
    )
    async def test_character_range_helper_rejects_invalid_bounds(
        self,
        offset: int,
        limit: int,
    ) -> None:
        """The lower-level character reader defends its own bounded contract."""
        storage = FakeSharedStorage({"/workspace/agent/text.txt": b"text"})

        with pytest.raises(ValueError, match="Character read range"):
            await _read_character_range(
                storage,
                "/workspace/agent/text.txt",
                agent_id="agent-1",
                offset=offset,
                limit=limit,
                encoding="utf-8",
            )

    async def test_unsupported_path(self) -> None:
        """Disallowed path raises FunctionToolError."""
        tool, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(json.dumps({"path": "/tmp/file.txt"}))

    async def test_file_not_found(self) -> None:
        """Nonexistent file raises FunctionToolError."""
        tool, _ = _make_tool(files={})
        with pytest.raises(FunctionToolError, match="File not found") as exc_info:
            await tool.handler(json.dumps({"path": "/workspace/agent/missing.txt"}))
        message = str(exc_info.value)
        assert "/workspace/agent" in message
        assert "import_file" not in message
        assert "present_file" not in message

    async def test_binary_file_utf8_decode_error(self) -> None:
        """Binary data raises a deterministic decode error."""
        # Given: binary data
        tool, _ = _make_tool(files={"/workspace/agent/binary.dat": b"\xff\xfe\x00\x01"})

        # When/Then: FunctionToolError
        with pytest.raises(FunctionToolError, match="cannot be decoded as utf-8"):
            await tool.handler(json.dumps({"path": "/workspace/agent/binary.dat"}))

    async def test_invalid_source_while_locating_offset_reports_decode_error(
        self,
    ) -> None:
        """Invalid bytes needed to locate an offset remain explicit errors."""
        data = (b"A" * (64 * 1024)) + b"\xffB"
        tool, _ = _make_tool(files={"/workspace/agent/invalid.txt": data})

        with pytest.raises(FunctionToolError, match="cannot be decoded as utf-8"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/invalid.txt",
                        "offset": 64 * 1024,
                        "limit": 1,
                    }
                )
            )

    async def test_invalid_unread_suffix_does_not_fail_bounded_range(self) -> None:
        """Bytes beyond the requested range and continuation probe stay unread."""
        tool, _ = _make_tool(files={"/workspace/agent/prefix.txt": b"AB\xff"})

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/prefix.txt",
                    "offset": 0,
                    "limit": 1,
                }
            )
        )

        assert isinstance(result, str)
        assert "\n\nA\n" in result
        assert "Use offset=1 to read more" in result

    async def test_unsupported_encoding_error_is_explicit(self) -> None:
        """Unknown encodings fail separately from invalid source bytes."""
        tool, _ = _make_tool(files={"/workspace/agent/text.txt": b"text"})

        with pytest.raises(FunctionToolError, match="Unsupported text encoding"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/text.txt",
                        "encoding": "not-an-encoding",
                    }
                )
            )
