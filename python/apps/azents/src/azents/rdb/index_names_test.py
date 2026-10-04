"""Deterministic explicit index name authoring contracts."""

import hashlib

import pytest

from azents.rdb.index_names import (
    INDEX_NAME_PREFIX_MAX_BYTES,
    POSTGRES_IDENTIFIER_MAX_BYTES,
    bounded_index_name,
    explicit_index_name,
    validate_index_name,
)


def test_fitting_names_are_unchanged_at_the_byte_limit() -> None:
    assert bounded_index_name("i" * 63) == "i" * 63
    assert (
        explicit_index_name(
            "projects",
            ["workspace_id"],
            unique_variant=False,
            predicate_variant=None,
            semantic_qualifiers=(),
        )
        == "ix_projects_workspace_id"
    )


def test_long_names_hash_the_complete_expansion() -> None:
    full = "i" * 64
    expected = "i" * 46 + "_" + hashlib.sha256(full.encode()).hexdigest()[:16]
    assert bounded_index_name(full) == expected
    assert bounded_index_name(full) == bounded_index_name(full)
    assert bounded_index_name(full + "a") != bounded_index_name(full + "b")
    assert INDEX_NAME_PREFIX_MAX_BYTES == 46
    assert POSTGRES_IDENTIFIER_MAX_BYTES == 63


@pytest.mark.parametrize("prefix", ["é" * 30, "한" * 20, "😀" * 15])
def test_prefix_never_splits_a_utf8_codepoint(prefix: str) -> None:
    full = "ix_" + prefix + "_tail"
    result = bounded_index_name(full)
    before_digest, digest = result.rsplit("_", 1)
    assert len(result.encode("utf-8")) <= 63
    assert len(before_digest.encode("utf-8")) <= 46
    assert full.startswith(before_digest)
    assert digest == hashlib.sha256(full.encode("utf-8")).hexdigest()[:16]


def test_same_column_variants_preserve_ordinary_name_and_sql_literal_identity() -> None:
    ordinary = explicit_index_name(
        "routes",
        ["connection_id"],
        unique_variant=False,
        predicate_variant=None,
        semantic_qualifiers=(),
    )
    predicate = "mode = 'single'"
    unique = explicit_index_name(
        "routes",
        ["connection_id"],
        unique_variant=True,
        predicate_variant=predicate,
        semantic_qualifiers=(),
    )
    assert ordinary == "ix_routes_connection_id"
    assert unique == (
        ordinary + "_unique_p" + hashlib.sha256(predicate.encode()).hexdigest()[:16]
    )
    assert unique != explicit_index_name(
        "routes",
        ["connection_id"],
        unique_variant=True,
        predicate_variant="mode = ' single '",
        semantic_qualifiers=(),
    )


def test_expression_ordering_has_explicit_semantic_qualifier() -> None:
    first = explicit_index_name(
        "sessions",
        ["cursor_id", "head_id"],
        unique_variant=False,
        predicate_variant=None,
        semantic_qualifiers=["asc_nulls_first"],
    )
    second = explicit_index_name(
        "sessions",
        ["cursor_id", "head_id"],
        unique_variant=False,
        predicate_variant=None,
        semantic_qualifiers=["desc_nulls_last"],
    )
    assert first == "ix_sessions_cursor_id_head_id_asc_nulls_first"
    assert first != second


def test_collision_and_overlong_identifiers_fail_without_fallback() -> None:
    with pytest.raises(ValueError, match="collides"):
        validate_index_name("ix_projects_workspace_id", {"ix_projects_workspace_id"})
    with pytest.raises(ValueError, match="byte limit"):
        validate_index_name("a" * 64, ())
    validate_index_name("ix_projects_workspace_id", {"projects"})
