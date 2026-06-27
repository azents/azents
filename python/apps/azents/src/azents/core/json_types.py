"""Shared JSON value type aliases."""

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JSONObject = dict[str, JsonValue]
