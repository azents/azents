"""Canonical shared json value contracts."""

type JSONScalar = str | int | float | bool | None


type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
