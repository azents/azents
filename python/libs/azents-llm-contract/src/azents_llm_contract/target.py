"""Deterministic target identity derived from existing Agent configuration."""

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class InferenceTarget:
    """A selected configuration identity, not an authorization capability."""

    label: str
    integration_id: str
    model_identifier: str

    def __post_init__(self) -> None:
        if not self.label or not self.integration_id or not self.model_identifier:
            raise ValueError("Target identity components must be nonempty.")

    @property
    def target_id(self) -> str:
        """Hash exact stored values without case folding or Unicode normalization."""
        material = json.dumps(
            [self.label, self.integration_id, self.model_identifier],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()
