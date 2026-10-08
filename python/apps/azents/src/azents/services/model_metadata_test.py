"""Exact current context requests never restore an entire source dataset."""

from collections.abc import Sequence

import pytest

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelContextWindow
from azents.engine.context.window import resolve_model_input_tokens
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source_data import (
    CapturedContextSource,
    ContextModelRequest,
    ModelMetadataSource,
)
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_metadata import (
    make_test_model_metadata_service,
    make_test_source,
    make_test_source_payload,
)
from azents.testing.model_selection import make_test_model_selection


class _CountingContextRepository(ModelMetadataReadRepository):
    def __init__(self, source: ModelMetadataSource | None) -> None:
        self.reader = make_test_model_metadata_service(source=source).repository
        self.requests: list[tuple[ContextModelRequest, ...]] = []

    async def capture_for_context(
        self, *, requests: Sequence[ContextModelRequest]
    ) -> CapturedContextSource:
        self.requests.append(tuple(requests))
        return await self.reader.capture_for_context(requests=requests)

    async def capture_current(self) -> ModelMetadataSource | None:
        raise AssertionError("Context resolution cannot read the full source.")


async def test_known_saved_maximum_skips_optional_database_read() -> None:
    selection = make_test_model_selection().model_copy(
        update={
            "normalized_capabilities": ModelCapabilities(
                context_window=ModelContextWindow(
                    default_input_tokens=128_000,
                    max_input_tokens=256_000,
                    max_output_tokens=None,
                ),
            )
        }
    )
    repository = _CountingContextRepository(None)
    service = ModelMetadataService(repository=repository)
    captured = await service.capture_for_context(
        requests=service.context_requests([selection])
    )
    assert captured.models == ()
    assert repository.requests == []


async def test_missing_pair_shares_one_exact_requested_read() -> None:
    repository = _CountingContextRepository(
        make_test_source(
            make_test_source_payload(
                {
                    "main": {
                        "litellm_provider": "openai",
                        "max_input_tokens": 1_000_000,
                    },
                    "compaction": {
                        "litellm_provider": "anthropic",
                        "max_input_tokens": 300_000,
                    },
                    "unrelated": {
                        "litellm_provider": "openai",
                        "max_input_tokens": 999_999,
                    },
                }
            )
        )
    )
    service = ModelMetadataService(repository=repository)
    requests = (
        ContextModelRequest(provider=LLMProvider.OPENAI, model_identifier="main"),
        ContextModelRequest(
            provider=LLMProvider.ANTHROPIC, model_identifier="compaction"
        ),
    )
    captured = await service.capture_for_context(requests=requests)
    assert repository.requests == [requests]
    assert len(captured.models) == 2
    assert {model.model_identifier for model in captured.models} == {
        "main",
        "compaction",
    }
    main = resolve_model_input_tokens(
        128_000,
        None,
        service.maximum_input_tokens(
            captured, provider=LLMProvider.OPENAI, model_identifier="main"
        ),
        700_000,
    )
    compaction = resolve_model_input_tokens(
        None,
        None,
        service.maximum_input_tokens(
            captured, provider=LLMProvider.ANTHROPIC, model_identifier="compaction"
        ),
        None,
    )
    assert main.effective_input_tokens == 700_000
    assert compaction.effective_input_tokens == 300_000


@pytest.mark.parametrize("identifier", ["absent", "openai/literal"])
async def test_exact_namespace_absence_has_no_model_name_fallback(
    identifier: str,
) -> None:
    source = make_test_source(
        make_test_source_payload(
            {
                "literal": {"litellm_provider": "openai", "max_input_tokens": 256_000},
            }
        )
    )
    service = make_test_model_metadata_service(source=source)
    captured = await service.capture_for_context(
        requests=[
            ContextModelRequest(
                provider=LLMProvider.OPENAI, model_identifier=identifier
            ),
            ContextModelRequest(
                provider=LLMProvider.CHATGPT_OAUTH, model_identifier="literal"
            ),
        ]
    )
    for model in captured.models:
        assert model.max_input_tokens is None
    assert (
        service.maximum_input_tokens(
            captured, provider=LLMProvider.OPENAI, model_identifier="literal"
        )
        is None
    )


@pytest.mark.parametrize(
    ("default", "saved_max", "source_max", "expected"),
    [
        (None, None, None, 128_000),
        (272_000, None, None, 272_000),
        (272_000, None, 128_000, 272_000),
        (128_000, None, 256_000, 256_000),
        (128_000, 200_000, 400_000, 200_000),
        (None, 256_000, None, 256_000),
    ],
)
def test_narrow_context_preserves_existing_floor_and_saved_authority(
    default: int | None, saved_max: int | None, source_max: int | None, expected: int
) -> None:
    limits = resolve_model_input_tokens(default, saved_max, source_max, None)
    assert limits.max_input_tokens == expected
    assert limits.effective_input_tokens == (
        default if default is not None else expected
    )


async def test_absent_current_source_remains_unavailable_without_other_authority() -> (
    None
):
    service = make_test_model_metadata_service(source=None)
    captured = await service.capture_for_context(
        requests=[
            ContextModelRequest(
                provider=LLMProvider.XAI_OAUTH, model_identifier="visible-model"
            ),
        ]
    )
    assert len(captured.models) == 1
    maximum = service.maximum_input_tokens(
        captured, provider=LLMProvider.XAI_OAUTH, model_identifier="visible-model"
    )
    assert maximum is None
    assert (
        resolve_model_input_tokens(272_000, None, maximum, None).max_input_tokens
        == 272_000
    )
