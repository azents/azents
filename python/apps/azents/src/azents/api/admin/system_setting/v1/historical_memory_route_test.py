"""Historical Memory execution Admin route and request contracts."""

import dataclasses
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from azents.api import admin
from azents.core.auth.deps import CurrentUser, SystemAdmin, get_current_user
from azents.core.historical_memory_system_setting import (
    HistoricalMemoryExecutionConfig,
    HistoricalMemoryExecutionSecrets,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingSection,
    SystemSettingVersionConflict,
)
from azents.core.system_setting_data import SystemSettingActivated
from azents.services.system_setting.service import SystemSettingsService
from azents.services.system_user_role.service import SystemUserRoleService
from azents.utils.fastapi.route import as_route_mounter

from . import (
    get_historical_memory_execution_setting,
    patch_historical_memory_execution_setting,
)
from .data import (
    HistoricalMemoryExecutionDetailResponse,
    HistoricalMemoryExecutionPatchRequest,
)


def _resolved(
    *, version: int, turns: int | None, timeout: int
) -> ResolvedSystemSetting:
    return ResolvedSystemSetting(
        section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
        schema_version=1,
        admin_version=version,
        config=HistoricalMemoryExecutionConfig(
            max_turns=turns, timeout_seconds=timeout
        ),
        secrets=HistoricalMemoryExecutionSecrets(),
        field_sources={},
        effective_generation="internal-generation",
    )


async def test_get_returns_defaults_without_internal_metadata() -> None:
    service = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    service.resolve = AsyncMock(
        return_value=_resolved(version=0, turns=None, timeout=600)
    )
    response = await get_historical_memory_execution_setting(service=service)
    service.resolve.assert_awaited_once_with(
        SystemSettingSection.HISTORICAL_MEMORY_EXECUTION
    )
    assert response.model_dump() == {
        "section": "historical_memory_execution",
        "schema_version": 1,
        "admin_version": 0,
        "max_turns": None,
        "timeout_seconds": 600,
    }


@pytest.mark.parametrize(
    "wire_payload",
    [
        {"expected_version": 3, "max_turns": None},
        {"expected_version": 3, "max_turns": 4},
        {"expected_version": 3, "timeout_seconds": 900},
        {"expected_version": 3, "max_turns": None, "timeout_seconds": 900},
    ],
)
async def test_patch_preserves_omission_and_explicit_null(
    wire_payload: dict[str, object],
) -> None:
    payload = TypeAdapter(HistoricalMemoryExecutionPatchRequest).validate_python(
        wire_payload
    )
    service = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    service.mutate = AsyncMock(
        return_value=SystemSettingActivated(
            current=Mock(), resolved=_resolved(version=4, turns=None, timeout=900)
        )
    )
    response = await patch_historical_memory_execution_setting(
        payload,
        system_admin=SystemAdmin(user_id="admin-1", session_id="session-1"),
        service=service,
    )
    call = service.mutate.await_args
    assert call is not None
    mutation = call.args[0]
    assert mutation.config_patch == {
        key: value for key, value in wire_payload.items() if key != "expected_version"
    }
    assert mutation.section is SystemSettingSection.HISTORICAL_MEMORY_EXECUTION
    assert mutation.expected_version == 3
    assert mutation.actor_user_id == "admin-1"
    assert mutation.secret_actions == {}
    assert response.admin_version == 4


async def test_patch_rejects_empty_without_mutation() -> None:
    service = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    with pytest.raises(HTTPException) as caught:
        await patch_historical_memory_execution_setting(
            {"expected_version": 0},
            system_admin=SystemAdmin(user_id="admin-1", session_id="session-1"),
            service=service,
        )
    assert caught.value.status_code == 422
    detail = caught.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "empty_system_setting_patch"
    service.mutate.assert_not_awaited()


async def test_patch_maps_stale_version_to_409() -> None:
    service = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    service.mutate = AsyncMock(
        side_effect=SystemSettingVersionConflict(
            section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
            expected_version=1,
            current_version=9,
        )
    )
    with pytest.raises(HTTPException) as caught:
        await patch_historical_memory_execution_setting(
            {"expected_version": 1, "max_turns": None},
            system_admin=SystemAdmin(user_id="admin-1", session_id="session-1"),
            service=service,
        )
    assert caught.value.status_code == 409
    detail = caught.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "stale_system_setting_version"
    assert detail["current_version"] == 9


async def test_patch_maps_effective_payload_validation_to_422() -> None:
    service = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    with pytest.raises(ValidationError) as invalid:
        HistoricalMemoryExecutionConfig(timeout_seconds=0)
    service.mutate = AsyncMock(side_effect=invalid.value)
    with pytest.raises(HTTPException) as caught:
        await patch_historical_memory_execution_setting(
            {"expected_version": 0, "timeout_seconds": 1},
            system_admin=SystemAdmin(user_id="admin-1", session_id="session-1"),
            service=service,
        )
    assert caught.value.status_code == 422
    detail = caught.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "invalid_system_setting_payload"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_version": -1, "max_turns": None},
        {"expected_version": 0, "max_turns": 0},
        {"expected_version": 0, "max_turns": True},
        {"expected_version": 0, "max_turns": "2"},
        {"expected_version": 0, "timeout_seconds": None},
        {"expected_version": 0, "timeout_seconds": 0},
        {"expected_version": 0, "timeout_seconds": True},
        {"expected_version": 0, "timeout_seconds": "600"},
        {"expected_version": 0, "timeout_seconds": 1.5},
        {"expected_version": 0, "unexpected": 1},
    ],
)
def test_patch_request_rejects_invalid_wire_payload(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(HistoricalMemoryExecutionPatchRequest).validate_python(payload)


@pytest.mark.parametrize("method", ["GET", "PATCH"])
@pytest.mark.parametrize("authenticated", [False, True])
def test_production_admin_mount_denies_unauthenticated_or_nonadmin(
    method: str, authenticated: bool
) -> None:
    """Both routes inherit the real secure Admin mounting default."""
    app = FastAPI()
    admin.mount(as_route_mounter(app))
    service = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    roles = create_autospec(SystemUserRoleService, instance=True, spec_set=True)
    roles.require_system_admin = AsyncMock(return_value=False)

    async def current_user() -> CurrentUser:
        if not authenticated:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return CurrentUser(user_id="user-1", session_id="session-1")

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[SystemUserRoleService] = lambda: roles
    app.dependency_overrides[SystemSettingsService] = lambda: service
    with TestClient(app) as client:
        response = client.request(
            method,
            "/system-setting/v1/sections/historical-memory-execution",
            json={"expected_version": 0, "max_turns": None}
            if method == "PATCH"
            else None,
        )
    assert response.status_code == (403 if authenticated else 401)
    service.resolve.assert_not_awaited()
    service.mutate.assert_not_awaited()


def test_detail_rejects_wrong_resolved_section_model() -> None:
    resolved = _resolved(version=0, turns=None, timeout=600)
    resolved = dataclasses.replace(resolved, config=HistoricalMemoryExecutionSecrets())
    with pytest.raises(TypeError, match="config model"):
        HistoricalMemoryExecutionDetailResponse.from_domain(resolved)


def test_authorized_http_reads_patches_and_rejects_invalid_input() -> None:
    """The real mounted routes validate wire bodies before service mutation."""
    app = FastAPI()
    admin.mount(as_route_mounter(app))
    service = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    service.resolve = AsyncMock(
        return_value=_resolved(version=0, turns=None, timeout=600)
    )
    service.mutate = AsyncMock(
        return_value=SystemSettingActivated(
            current=Mock(), resolved=_resolved(version=1, turns=None, timeout=600)
        )
    )
    roles = create_autospec(SystemUserRoleService, instance=True, spec_set=True)
    roles.require_system_admin = AsyncMock(return_value=True)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="admin-1", session_id="session-1"
    )
    app.dependency_overrides[SystemUserRoleService] = lambda: roles
    app.dependency_overrides[SystemSettingsService] = lambda: service
    path = "/system-setting/v1/sections/historical-memory-execution"
    with TestClient(app) as client:
        initial = client.get(path)
        assert initial.status_code == 200
        detail = HistoricalMemoryExecutionDetailResponse.model_validate(initial.json())
        assert detail.max_turns is None
        assert detail.timeout_seconds == 600
        assert detail.admin_version == 0
        patched = client.patch(path, json={"expected_version": 0, "max_turns": None})
        assert patched.status_code == 200
        assert (
            HistoricalMemoryExecutionDetailResponse.model_validate(
                patched.json()
            ).admin_version
            == 1
        )
        for payload in (
            {"expected_version": 1, "timeout_seconds": None},
            {"expected_version": 1, "max_turns": False},
            {"expected_version": 1, "timeout_seconds": 0},
        ):
            assert client.patch(path, json=payload).status_code == 422
    service.resolve.assert_awaited_once()
    service.mutate.assert_awaited_once()
