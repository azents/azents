---
title: "Declare explicit canonical index names, qualify same-column semantic variants, and bound PostgreSQL identifiers to 63 UTF-8 bytes with a deterministic SHA-256 suffix."
---

# Explicit PostgreSQL-safe Index Names

- Define indexes explicitly; avoid `mapped_column(index=True)`.
- Start with `ix_{table}_{ordered_columns}`. Keep a fitting ordinary canonical name unchanged.
- If different definitions share ordered columns, qualify the variant before byte bounding: `_unique` for differing uniqueness and `_p{sha256(predicate_utf8)[:16]}` for a partial predicate. Use the declaration's explicit PostgreSQL expression text (literal binds for expression trees), not driver output; preserve SQL literals exactly. Other differing facets require an explicit semantic qualifier.
- For an expansion over 63 UTF-8 bytes, keep the longest complete-codepoint prefix fitting 46 bytes, then `_` and the first 16 lowercase hex digits of SHA-256 of the **full expanded UTF-8 name**. Never rely on database/dialect truncation.
- Validate uniqueness against every relation in the owning schema. A collision fails validation; do not overwrite, add counters, or assume `IF NOT EXISTS` means equivalent definitions.
- Keep the exact same explicit name in ORM, native-generated forward migration and name consumers. Preserve ordered columns, uniqueness, predicates and other options; historical migrations stay unchanged.

## Examples

- Ordinary: `ix_projects_workspace_id`
- Same-column unique variant: `ix_projects_workspace_id_unique`
- Long: `utf8_prefix_46_bytes + "_" + sha256(full_expansion.encode("utf-8")).hexdigest()[:16]`

PostgreSQL's limit is bytes, including quoted names, and indexes share the schema relation namespace. See [identifier limits](https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS) and [CREATE INDEX](https://www.postgresql.org/docs/current/sql-createindex.html).
