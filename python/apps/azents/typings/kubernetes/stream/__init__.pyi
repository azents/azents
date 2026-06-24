"""kubernetes.stream — exec/attach/portforward 스트리밍 API 타입 보강."""

from collections.abc import Callable
from typing import Any

def stream(func: Callable[..., Any], **kwargs: Any) -> str: ...
