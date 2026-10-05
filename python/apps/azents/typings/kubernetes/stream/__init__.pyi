"""kubernetes.stream — exec/attach/portforward streaming API type extensions."""

from collections.abc import Callable
from typing import Any

def stream(func: Callable[..., Any], **kwargs: Any) -> str: ...
