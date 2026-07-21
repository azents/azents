"""Provider-neutral client tool wire contract types."""

from typing import Literal, TypeAlias

ClientToolWireDialect: TypeAlias = Literal["json_function", "plaintext_custom"]
