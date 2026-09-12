"""Detached results for private external model-setting operations."""

import dataclasses

from azents.core.external_model_settings import (
    ExternalModelApplyResult,
    ExternalModelCancelResult,
    ExternalModelEditorResult,
    ExternalModelNoticePlan,
)


@dataclasses.dataclass(frozen=True)
class ExternalModelApplyCommit:
    """Committed Apply result and first-commit process-local notice plan."""

    result: ExternalModelApplyResult
    notice_plan: ExternalModelNoticePlan | None


@dataclasses.dataclass(frozen=True)
class ExternalModelNoticeDeliveryContext:
    """Committed notice plus encrypted provider credential material."""

    plan: ExternalModelNoticePlan
    encrypted_credentials: str


ExternalModelOpenResult = ExternalModelEditorResult
ExternalModelUpdateResult = ExternalModelEditorResult
ExternalModelPageResult = ExternalModelEditorResult
ExternalModelCancellation = ExternalModelCancelResult
