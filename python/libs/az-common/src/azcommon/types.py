from typing_extensions import TypeAliasType

#: JSON-compatible scalar types.
JSONScalar = str | int | float | bool | None
# Using TypeAliasType to define a self-contained type
# https://docs.pydantic.dev/2.11/concepts/types/#named-type-aliases
#: JSON-compatible type.
JSONValue = TypeAliasType(
    "JSONValue", "JSONScalar | dict[str, JSONValue] | list[JSONValue]"
)
#: JSON-compatible dictionary type.
JSONObject = dict[str, JSONValue]
#: JSON-compatible list type.
JSONList = list[JSONValue]
