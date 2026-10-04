"""Pure authoring rules for explicit PostgreSQL index identifiers."""

import hashlib
from collections.abc import Collection, Sequence

POSTGRES_IDENTIFIER_MAX_BYTES = 63
INDEX_NAME_DIGEST_HEX_LENGTH = 16
INDEX_NAME_PREFIX_MAX_BYTES = (
    POSTGRES_IDENTIFIER_MAX_BYTES - 1 - INDEX_NAME_DIGEST_HEX_LENGTH
)


def bounded_index_name(expanded_name: str) -> str:
    """Keep a fitting identifier or retain its UTF-8-safe prefix and digest."""
    encoded = expanded_name.encode("utf-8")
    if len(encoded) <= POSTGRES_IDENTIFIER_MAX_BYTES:
        return expanded_name
    prefix = encoded[:INDEX_NAME_PREFIX_MAX_BYTES].decode("utf-8", errors="ignore")
    digest = hashlib.sha256(encoded).hexdigest()[:INDEX_NAME_DIGEST_HEX_LENGTH]
    return f"{prefix}_{digest}"


def explicit_index_name(
    table_name: str,
    ordered_columns: Sequence[str],
    *,
    unique_variant: bool,
    predicate_variant: str | None,
    semantic_qualifiers: Sequence[str],
) -> str:
    """Derive an explicit name, qualifying only same-column semantic variants.

    The predicate is the declaration's exact PostgreSQL expression text, not
    database-rendered output. Callers persist this result as a literal in the
    ORM and migration; this function does not inspect or modify database state.
    """
    expanded = f"ix_{table_name}_{'_'.join(ordered_columns)}"
    if unique_variant:
        expanded += "_unique"
    if predicate_variant is not None:
        digest = hashlib.sha256(predicate_variant.encode("utf-8")).hexdigest()
        expanded += f"_p{digest[:INDEX_NAME_DIGEST_HEX_LENGTH]}"
    for qualifier in semantic_qualifiers:
        expanded += f"_{qualifier}"
    return bounded_index_name(expanded)


def validate_index_name(name: str, existing_relations: Collection[str]) -> None:
    """Reject a byte-limit or schema relation collision without inventing names."""
    if len(name.encode("utf-8")) > POSTGRES_IDENTIFIER_MAX_BYTES:
        raise ValueError("Index identifier exceeds PostgreSQL's byte limit")
    if name in existing_relations:
        raise ValueError("Index identifier collides with an existing schema relation")
