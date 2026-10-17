"""Canonical personal GitHub runtime delegation is not Workspace manager authority."""

import dataclasses
import json
from unittest.mock import AsyncMock

import pytest

from azents.core.github_user_oauth import GitHubUserOAuthError
from azents.core.github_user_runtime import GitHubUserExecutionContext
from azents.core.personal_toolkit import PersonalToolkitAccessMutation
from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.repos.github_user_oauth.personal_test import prepare, review
from azents.repos.github_user_oauth.runtime import GitHubUserRuntimeOperationRepository
from azents.repos.toolkit.personal_management_test import Harness as ManagementHarness
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- current management operations
)
from azents.repos.toolkit.personal_runtime_test import Harness as RuntimeHarness
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- single real PostgreSQL ownership foundation
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- root/subagent authority and cleanup
)
from azents.services.github_user_oauth.runtime import GitHubUserRuntimeService


async def test_personal_user_grant_follows_root_and_current_policy_without_fallback(
    harness: ManagementHarness,
    runtime: RuntimeHarness,
) -> None:
    setup = await prepare(harness)
    configured = await harness.foundation.operations.update(
        user_id=harness.subject.user_id,
        workspace_id=harness.subject.workspace_id,
        toolkit_id=setup.requester.toolkit_id,
        update={
            "credentials": json.dumps(
                {
                    "type": "github_app_user",
                    "app_id": setup.registration.app_id,
                    "client_id": setup.registration.client_id,
                    "client_secret": setup.registration.client_secret,
                    "private_key": "fixture-private-key",
                }
            )
        },
    )
    setup = dataclasses.replace(
        setup,
        registration=dataclasses.replace(
            setup.registration, toolkit_revision=configured.revision
        ),
    )
    attempt = await review(setup, "fixture-personal-github-token")
    await setup.operations.confirm(
        requester=setup.requester, attempt_id=attempt, registration=setup.registration
    )
    root = await runtime.root(harness.subject.user_id, 0)
    [source] = await runtime.sources(root)
    assert harness.foundation.repository.cipher is not None
    operations = GitHubUserRuntimeOperationRepository(
        harness.foundation.writes,
        harness.repository.shared_operations.toolkit_repository,
        harness.foundation.repository.cipher,
    )
    service = GitHubUserRuntimeService(operations, AsyncMock())
    context = GitHubUserExecutionContext(
        root.workspace_id,
        root.agent_id,
        root.owner.session_id,
        source.toolkit.id,
        "byoa_user",
        setup.registration.app_id,
        setup.registration.client_id,
        source.target,
    )
    first = await service.current_connection(context)
    assert first.access_token == "fixture-personal-github-token"
    assert await service.runtime_environment(context) == {
        "GH_TOKEN": first.access_token,
        "GITHUB_TOKEN": first.access_token,
    }
    with pytest.raises(GitHubUserOAuthError):
        await service.current_connection(
            dataclasses.replace(context, personal_target=None)
        )
    team = await runtime.root(None, 0)
    with pytest.raises(GitHubUserOAuthError):
        await service.current_connection(
            dataclasses.replace(context, session_id=team.owner.session_id)
        )
    child = await runtime.child(root, root.node_id)
    [child_source] = await runtime.sources(child)
    child_context = dataclasses.replace(
        context, session_id=child.owner.session_id, personal_target=child_source.target
    )
    assert (await service.current_connection(child_context)).id == first.id
    await harness.service.mutate_access(
        harness.subject,
        [
            PersonalToolkitAccessMutation(
                source.toolkit.id,
                None,
                frozenset(),
                frozenset([root.agent_id]),
                Mode.ALL,
            )
        ],
        agent_id=None,
    )
    for target in [context, child_context]:
        with pytest.raises(GitHubUserOAuthError):
            await service.current_connection(target)
        with pytest.raises(GitHubUserOAuthError):
            await service.runtime_environment(target)
    # A late rejected request cannot change the grant after its source is withdrawn.
    await service.authentication_failed(context, connection_id=first.id)
    still_connected = await setup.operations.read_context(requester=setup.requester)
    assert still_connected.connection is not None
    assert still_connected.connection.status == first.status
