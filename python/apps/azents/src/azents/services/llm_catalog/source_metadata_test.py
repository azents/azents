"""Package-free retained-source decoding and configuration tests."""

import subprocess
import sys
import textwrap

import pytest
from pydantic import ValidationError

from azents.services.llm_catalog import _get_litellm_source_url
from azents.services.llm_catalog.source_metadata import SourceReasoningMetadata


def test_reasoning_source_defaults_remain_unknown() -> None:
    """Absent and explicit null flags do not advertise reasoning support."""
    missing = SourceReasoningMetadata.model_validate({})
    explicit_null = SourceReasoningMetadata.model_validate(
        {"supports_reasoning": None, "supports_low_reasoning_effort": None}
    )
    assert missing == explicit_null
    assert missing.supports_reasoning is None
    assert missing.supports_low_reasoning_effort is None


def test_reasoning_source_keeps_flag_coercion_and_ignores_unconsumed_fields() -> None:
    """Keep the consumed schema's bool decoding without editing source content."""
    payload = {
        "supports_reasoning": "true",
        "supports_low_reasoning_effort": "false",
        "source_extension": {"arbitrary": [1, 2, 3]},
        "input_cost_per_token": 0.000001,
    }
    decoded = SourceReasoningMetadata.model_validate(payload)
    assert decoded.supports_reasoning is True
    assert decoded.supports_low_reasoning_effort is False
    assert payload["supports_reasoning"] == "true"
    assert payload["source_extension"] == {"arbitrary": [1, 2, 3]}


def test_reasoning_source_rejects_invalid_consumed_flag() -> None:
    """An invalid reasoning flag remains a projection validation error."""
    with pytest.raises(ValidationError):
        SourceReasoningMetadata.model_validate({"supports_reasoning": {"bad": True}})


def test_retained_source_url_defaults_without_installed_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owned composition root keeps the original public dataset default."""
    monkeypatch.delenv("LITELLM_MODEL_COST_MAP_URL", raising=False)
    assert _get_litellm_source_url() == (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )


def test_retained_source_url_honors_existing_environment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read the existing source override without another config authority."""
    source_url = "https://catalog.example.test/custom/models.json"
    monkeypatch.setenv("LITELLM_MODEL_COST_MAP_URL", source_url)
    assert _get_litellm_source_url() == source_url


def test_source_collection_and_projection_do_not_import_retired_package() -> None:
    """A fresh interpreter can collect and project while LiteLLM is unavailable."""
    program = textwrap.dedent(
        """
        import asyncio
        import datetime
        import importlib.abc
        import sys

        class BlockRetiredPackage(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "litellm" or fullname.startswith("litellm."):
                    raise ModuleNotFoundError("retired package is unavailable")
                return None

        sys.meta_path.insert(0, BlockRetiredPackage())
        import httpx
        from azents.core.enums import LLMProvider
        from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
        from azents.services.llm_catalog import (
            LiteLLMSourceLoader,
            project_system_entries,
        )

        payload = {
            "openai/canonical": {
                "litellm_provider": "openai",
                "mode": "chat",
                "supports_reasoning": True,
                "aliases": ["openai/alias"],
                "unconsumed_metadata": {"kept": ["as-is"]},
            }
        }
        requests = 0
        def handler(request):
            global requests
            requests += 1
            return httpx.Response(200, json=payload, request=request)

        async def run():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                loader = LiteLLMSourceLoader(
                    http_client=client, source_url="https://catalog.example.test/models.json"
                )
                source = await loader.fetch_remote()
            assert set(source) == {"openai/canonical", "openai/alias"}
            assert source["openai/canonical"]["unconsumed_metadata"] == {
                "kept": ["as-is"]
            }
            snapshot = LiteLLMSourceSnapshot(
                id="source-id", source_key="litellm_model_cost", source_url=None,
                source_hash="hash", model_count=2, litellm_version=None,
                loaded_source="remote", payload=source,
                created_at=datetime.datetime.now(datetime.UTC),
            )
            entries = project_system_entries(
                provider=LLMProvider.OPENAI, source_snapshot=snapshot
            )
            assert len(entries) == 2
            for entry in entries:
                reasoning = entry.normalized_capabilities["reasoning"]
                assert reasoning["supported"] is True
                assert reasoning["effort_levels"] == ["low", "medium", "high"]
            assert requests == 1
            assert not any(
                name == "litellm" or name.startswith("litellm.")
                for name in sys.modules
            )

        asyncio.run(run())
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
