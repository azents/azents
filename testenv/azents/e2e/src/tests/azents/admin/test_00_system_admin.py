"""System bootstrap and live system-administrator authorization E2E tests."""

from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.debug_v1_api import DebugV1Api
from azentsadminclient.api.system_v1_api import SystemV1Api
from azentsadminclient.api.user_v1_api import UserV1Api as AdminUserV1Api
from azentspublicclient.api.user_v1_api import UserV1Api as PublicUserV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from testcontainers.core.container import DockerContainer

from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import authenticate_user, unique


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_id_by_email(
    admin_api_client: azentsadminclient.ApiClient,
    email: str,
) -> str:
    users = AdminUserV1Api(admin_api_client).user_v1_list_users(limit=1000)
    for user in users.items:
        if user.primary_email == email:
            return user.id
    raise AssertionError("created user was not returned by the Admin API")


def _assert_api_status(error: azentsadminclient.ApiException, expected: int) -> None:
    assert cast(Any, error).status == expected


def _client_for_token(
    admin_server_url: str,
    access_token: str,
) -> azentsadminclient.ApiClient:
    return azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=admin_server_url,
            access_token=access_token,
        )
    )


def test_configured_bootstrap_is_concurrent_safe_and_workspace_free(
    system_bootstrap_evidence: SystemBootstrapEvidence,
    public_api_client: azentspublicclient.ApiClient,
) -> None:
    """One configured-token bootstrap wins and creates no Workspace."""
    assert system_bootstrap_evidence.initial_available is True
    assert system_bootstrap_evidence.invalid_attempt_status == 403
    assert system_bootstrap_evidence.concurrent_attempt_statuses == (201, 403)
    assert system_bootstrap_evidence.final_available is False

    workspaces = WorkspaceV1Api(public_api_client).workspace_v1_list_workspaces(
        _headers=_authorization(system_bootstrap_evidence.access_token)
    )
    assert workspaces.items == []


def test_live_role_grant_revoke_and_final_admin_invariants(
    azents_admin_server_container: DockerContainer,
    azents_admin_server_url: str,
    admin_api_client: azentsadminclient.ApiClient,
    public_api_client: azentspublicclient.ApiClient,
) -> None:
    """Persisted system roles gate existing tokens and protect the final admin."""
    ordinary_token, _, ordinary_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"ordinary-admin-check-{unique()}@example.com",
    )
    ordinary_user_id = _user_id_by_email(admin_api_client, ordinary_email)

    with _client_for_token(azents_admin_server_url, ordinary_token) as ordinary_client:
        ordinary_system_api = SystemV1Api(ordinary_client)
        with pytest.raises(azentsadminclient.ApiException) as denied_me:
            ordinary_system_api.system_v1_get_system_admin_me()
        _assert_api_status(denied_me.value, 403)

        with pytest.raises(azentsadminclient.ApiException) as denied_debug:
            DebugV1Api(ordinary_client).debug_v1_fire_log(
                message="ordinary user must not reach Debug"
            )
        _assert_api_status(denied_debug.value, 403)

        system_api = SystemV1Api(admin_api_client)
        system_api.system_v1_grant_system_admin(ordinary_user_id)
        assert (
            ordinary_system_api.system_v1_get_system_admin_me().user_id
            == ordinary_user_id
        )
        assert (
            "system_admin"
            in PublicUserV1Api(public_api_client)
            .user_v1_get_my_system_roles(_headers=_authorization(ordinary_token))
            .roles
        )

        system_api.system_v1_revoke_system_admin(ordinary_user_id)
        with pytest.raises(azentsadminclient.ApiException) as revoked_me:
            ordinary_system_api.system_v1_get_system_admin_me()
        _assert_api_status(revoked_me.value, 403)
        assert (
            PublicUserV1Api(public_api_client)
            .user_v1_get_my_system_roles(_headers=_authorization(ordinary_token))
            .roles
            == []
        )

        cli_result = azents_admin_server_container.get_wrapped_container().exec_run(
            [
                "python",
                "src/cli/system_admin.py",
                "grant",
                "--email",
                ordinary_email,
            ]
        )
        if cast(Any, cli_result).exit_code != 0:
            raise AssertionError("system-admin CLI grant failed")
        assert (
            ordinary_system_api.system_v1_get_system_admin_me().user_id
            == ordinary_user_id
        )
        system_api.system_v1_revoke_system_admin(ordinary_user_id)

        missing_cli_result = (
            azents_admin_server_container.get_wrapped_container().exec_run(
                [
                    "python",
                    "src/cli/system_admin.py",
                    "grant",
                    "--email",
                    f"missing-{unique()}@example.com",
                ]
            )
        )
        assert cast(Any, missing_cli_result).exit_code != 0

    system_api = SystemV1Api(admin_api_client)
    initial_admin_id = system_api.system_v1_get_system_admin_me().user_id
    with pytest.raises(azentsadminclient.ApiException) as final_revoke:
        system_api.system_v1_revoke_system_admin(initial_admin_id)
    _assert_api_status(final_revoke.value, 409)

    admin_user_api = AdminUserV1Api(admin_api_client)
    with pytest.raises(azentsadminclient.ApiException) as final_delete:
        admin_user_api.user_v1_delete_user(initial_admin_id)
    _assert_api_status(final_delete.value, 409)

    _, _, deletable_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"deletable-admin-{unique()}@example.com",
    )
    deletable_user_id = _user_id_by_email(admin_api_client, deletable_email)
    system_api.system_v1_grant_system_admin(deletable_user_id)
    admin_user_api.user_v1_delete_user(deletable_user_id)

    with pytest.raises(azentsadminclient.ApiException) as deleted_user:
        admin_user_api.user_v1_get_user(deletable_user_id)
    _assert_api_status(deleted_user.value, 404)
    assignments = system_api.system_v1_list_system_role_assignments(limit=100)
    assert all(item.user_id != deletable_user_id for item in assignments.items)
