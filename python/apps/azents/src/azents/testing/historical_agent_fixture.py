"""Agent seed frozen to the schema used by predecessor migration tests."""

import json

import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.enums import LLMProvider
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session_capabilities import WriteSession
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


async def create_historical_agent(
    session: WriteSession,
    *,
    workspace_id: str,
    name: str,
) -> str:
    """Seed predecessor Agent columns without importing today's Agent ORM mapping."""
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{name}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.write_session.add(integration)
    await session.write_session.flush()
    model = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier=f"{name}-model",
    )
    options = make_test_selectable_model_option_dicts(
        model_selection=model, lightweight_model_selection=model
    )
    agent_id = uuid7().hex
    await session.write_session.execute(
        sa.text("""
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label,
                enabled, memory_enabled, runtime_capability, type
            ) VALUES (
                :id, :workspace, :name, CAST(:model AS jsonb), CAST(:model AS jsonb),
                CAST(:options AS jsonb), 'default', 'lightweight',
                true, true, 'managed', 'public'
            )
        """),
        {
            "id": agent_id,
            "workspace": workspace_id,
            "name": name,
            "model": json.dumps(model),
            "options": json.dumps(options),
        },
    )
    return agent_id
