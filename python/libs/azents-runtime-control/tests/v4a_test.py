"""Shared strict grammar and applicability without any filesystem adapter."""

import pytest

from azents_runtime_control.v4a import (
    ApplyPatchLimits,
    V4aPatchError,
    apply_update,
    decode_source_text,
    parse_patch,
)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("final_newline", [False, True])
def test_exact_update_preserves_native_newlines(
    newline: str, final_newline: bool
) -> None:
    plan = parse_patch(
        b"*** Begin Patch\n*** Update File: doc.md\n@@\n-old\n+new\n*** End Patch\n"
    )
    operation = plan.operations[0]
    data = ("old" + (newline if final_newline else "")).encode()
    source = decode_source_text(data, operation=operation, max_bytes=100, remaining=())
    updated = apply_update(operation, source)
    assert updated.output == ("new" + (newline if final_newline else "")).encode()
    assert updated.added_lines == updated.removed_lines == 1


@pytest.mark.parametrize(
    "path,reason",
    [
        ("../escape", "invalid_path_component"),
        ("/absolute", "absolute_path"),
        ("a//b", "invalid_path_component"),
    ],
)
def test_relative_target_contract(path: str, reason: str) -> None:
    with pytest.raises(V4aPatchError) as error:
        parse_patch(
            f"*** Begin Patch\n*** Add File: {path}\n+new\n*** End Patch\n".encode()
        )
    assert error.value.phase == "parse" and error.value.reason == reason


def test_parse_limits_and_binary_rejection() -> None:
    patch = b"*** Begin Patch\n*** Add File: a\n+new\n*** End Patch\n"
    with pytest.raises(V4aPatchError) as error:
        parse_patch(patch, limits=ApplyPatchLimits(max_patch_bytes=8))
    assert error.value.reason == "patch_too_large"
    with pytest.raises(V4aPatchError) as binary:
        parse_patch(patch.replace(b"new", b"\x00"))
    assert binary.value.reason == "invalid_encoding"


def test_ambiguous_applicability_retains_source() -> None:
    operation = parse_patch(
        b"*** Begin Patch\n*** Update File: a\n@@\n-old\n+new\n*** End Patch\n"
    ).operations[0]
    source = decode_source_text(
        b"old\nold\n", operation=operation, max_bytes=100, remaining=()
    )
    with pytest.raises(V4aPatchError) as error:
        apply_update(operation, source)
    assert error.value.reason == "ambiguous_context"
    assert source.data == b"old\nold\n"
