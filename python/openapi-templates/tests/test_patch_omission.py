"""Shared regressions for native Public/Admin client generation and wire bodies."""

import json
import unittest
from typing import NamedTuple

from azentsadminclient.api_client import ApiClient as AdminApiClient
from azentsadminclient.models.external_account_o_auth_patch_request import (
    ExternalAccountOAuthPatchRequest,
)
from azentsadminclient.models.external_account_o_auth_secret_action_request import (
    ExternalAccountOAuthSecretActionRequest,
)
from azentsadminclient.models.historical_memory_execution_patch_request import (
    HistoricalMemoryExecutionPatchRequest,
)
from azentsadminclient.models.runtime_provider_operational_warning_response import (
    RuntimeProviderOperationalWarningResponse,
)
from azentspublicclient.api_client import ApiClient as PublicApiClient
from azentspublicclient.models.agent_update_request import AgentUpdateRequest
from azentspublicclient.models.runtime_web_update_request import RuntimeWebUpdateRequest
from azentspublicclient.models.selectable_model_candidate_input import (
    SelectableModelCandidateInput,
)
from azentspublicclient.models.selectable_model_option_input import (
    SelectableModelOptionInput,
)
from azentspublicclient.models.subagent_settings import SubagentSettings
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from azentspublicclient.models.workspace_model_settings_update_request import (
    WorkspaceModelSettingsUpdateRequest,
)
from pydantic import ValidationError

type PatchModel = (
    AgentUpdateRequest
    | WorkspaceModelSettingsUpdateRequest
    | RuntimeWebUpdateRequest
    | HistoricalMemoryExecutionPatchRequest
)


class PatchCase(NamedTuple):
    model: type[PatchModel]
    required: dict[str, object]
    nullable: str
    client: PublicApiClient | AdminApiClient


class TestPatchOmission(unittest.TestCase):
    """Exercise constructors, decoded input, and the actual ApiClient serializer."""

    def setUp(self) -> None:
        self.cases = (
            PatchCase(AgentUpdateRequest, {}, "description", PublicApiClient()),
            PatchCase(
                WorkspaceModelSettingsUpdateRequest,
                {},
                "default_main_model_label",
                PublicApiClient(),
            ),
            PatchCase(
                RuntimeWebUpdateRequest,
                {"expected_revision": 0, "operation_key": "test"},
                "label",
                PublicApiClient(),
            ),
            PatchCase(
                HistoricalMemoryExecutionPatchRequest,
                {"expected_version": 1},
                "max_turns",
                AdminApiClient(),
            ),
        )

    def test_omission_matches_direct_validation_and_wire_body(self) -> None:
        for case in self.cases:
            with self.subTest(model=case.model.__name__):
                direct = case.model.model_validate(case.required)
                converted = case.model.from_dict(case.required)
                via_json = case.model.from_json(json.dumps(case.required))
                assert converted is not None
                assert via_json is not None
                self.assertEqual(converted.model_fields_set, set(case.required))
                self.assertEqual(via_json.model_fields_set, direct.model_fields_set)
                self.assertEqual(converted.to_dict(), case.required)
                self.assertEqual(via_json.to_dict(), direct.to_dict())
                self.assertEqual(json.loads(converted.to_json()), case.required)
                self.assertEqual(
                    case.client.sanitize_for_serialization(converted), case.required
                )

    def test_explicit_null_remains_present_without_other_nulls(self) -> None:
        for case in self.cases:
            with self.subTest(model=case.model.__name__):
                payload = {**case.required, case.nullable: None}
                converted = case.model.from_dict(payload)
                via_json = case.model.from_json(json.dumps(payload))
                assert converted is not None
                assert via_json is not None
                self.assertEqual(converted.model_fields_set, set(payload))
                self.assertEqual(converted.to_dict(), payload)
                self.assertEqual(via_json.to_dict(), payload)
                self.assertEqual(
                    case.client.sanitize_for_serialization(converted), payload
                )

    def test_explicit_constructors_preserve_omission_for_all_four_models(self) -> None:
        self.assertEqual(AgentUpdateRequest().to_dict(), {})
        self.assertEqual(WorkspaceModelSettingsUpdateRequest().to_dict(), {})
        self.assertEqual(
            RuntimeWebUpdateRequest(
                expected_revision=0, operation_key="test"
            ).to_dict(),
            {"expected_revision": 0, "operation_key": "test"},
        )
        self.assertEqual(
            HistoricalMemoryExecutionPatchRequest(expected_version=1).to_dict(),
            {"expected_version": 1},
        )

    def test_unknown_keys_keep_existing_closed_model_policy(self) -> None:
        for case in self.cases:
            with self.subTest(model=case.model.__name__):
                converted = case.model.from_dict(
                    {**case.required, "unknown_provider_extension": {"opaque": True}}
                )
                assert converted is not None
                self.assertEqual(converted.model_fields_set, set(case.required))
                self.assertEqual(converted.to_dict(), case.required)

    def test_missing_required_keys_still_fail_validation(self) -> None:
        for case in self.cases:
            if not case.required:
                continue
            for key in case.required:
                with self.subTest(model=case.model.__name__, missing=key):
                    payload = {k: v for k, v in case.required.items() if k != key}
                    with self.assertRaises(ValidationError):
                        case.model.from_dict(payload)

    def test_false_empty_and_zero_values_remain_supplied(self) -> None:
        payload = {
            "description": "",
            "enabled": False,
            "max_turns": 0,
            "selectable_model_options": [],
            "model_parameters": {},
        }
        converted = AgentUpdateRequest.from_dict(payload)
        assert converted is not None
        self.assertEqual(converted.model_fields_set, set(payload))
        self.assertEqual(converted.to_dict(), payload)
        self.assertEqual(
            PublicApiClient().sanitize_for_serialization(converted), payload
        )
        admin = HistoricalMemoryExecutionPatchRequest.from_dict(
            {"expected_version": 0, "max_turns": 1, "timeout_seconds": 1}
        )
        assert admin is not None
        self.assertEqual(admin.to_dict()["expected_version"], 0)

    def test_public_nested_objects_and_arrays_keep_recursive_omission(self) -> None:
        candidate = {
            "model_selection": {
                "llm_provider_integration_id": "integration",
                "model_identifier": "model",
            }
        }
        payload = {
            "selectable_model_options": [
                {"label": "primary", "candidates": [candidate]}
            ],
            "subagent_settings": {"max_subagents": 0},
        }
        converted = AgentUpdateRequest.from_dict(payload)
        assert converted is not None
        options = converted.selectable_model_options
        assert options is not None
        self.assertIsInstance(options[0], SelectableModelOptionInput)
        self.assertIsInstance(options[0].candidates[0], SelectableModelCandidateInput)
        self.assertEqual(options[0].model_fields_set, {"label", "candidates"})
        self.assertEqual(options[0].candidates[0].model_fields_set, set(candidate))
        settings = converted.subagent_settings
        assert settings is not None
        self.assertEqual(settings.model_fields_set, {"max_subagents"})
        self.assertEqual(settings.max_subagents, 0)
        self.assertEqual(settings.max_depth, 1)
        self.assertNotIn(
            "subagent_guidance", converted.to_dict()["selectable_model_options"][0]
        )
        via_json = AgentUpdateRequest.from_json(json.dumps(payload))
        assert via_json is not None
        self.assertEqual(via_json.to_dict(), converted.to_dict())

    def test_admin_nested_and_additional_properties_keep_original_conversion(
        self,
    ) -> None:
        payload = {
            "expected_version": 0,
            "client_secret": {"action": "replace", "value": "secret"},
            "provider_extension": {"nested": [False, None, ""]},
        }
        converted = ExternalAccountOAuthPatchRequest.from_dict(payload)
        assert converted is not None
        secret = converted.client_secret
        self.assertIsInstance(secret, ExternalAccountOAuthSecretActionRequest)
        assert secret is not None
        self.assertEqual(secret.model_fields_set, {"action", "value"})
        self.assertEqual(
            converted.additional_properties,
            {"provider_extension": {"nested": [False, None, ""]}},
        )
        self.assertEqual(converted.to_dict(), payload)
        self.assertEqual(
            AdminApiClient().sanitize_for_serialization(converted), payload
        )

    def test_omitted_defaults_follow_model_defaults(self) -> None:
        for model in (SubagentSettings,):
            with self.subTest(model=model.__module__):
                converted = model.from_dict({})
                assert converted is not None
                self.assertEqual(converted.model_fields_set, set())
                self.assertEqual(converted.max_subagents, 3)
                self.assertEqual(converted.max_depth, 1)
                self.assertEqual(converted.to_dict(), model().to_dict())

    def test_nullable_outer_input_keeps_original_behavior(self) -> None:
        for case in self.cases:
            with self.subTest(model=case.model.__name__):
                self.assertIsNone(case.model.from_dict(None))

    def test_mapping_values_preserve_nested_json_and_admin_string_map(self) -> None:
        payload = {
            "toolkit_type": "mcp",
            "config": {"nested": {"entries": [False, None, ""]}},
        }
        public = ToolkitConfigCreateRequest.from_dict(payload)
        assert public is not None
        self.assertEqual(public.config, payload["config"])
        self.assertEqual(public.model_fields_set, set(payload))
        admin_payload = {
            "code": "deployment_warning",
            "severity": "warning",
            "metadata": {"namespace": "", "name": "provider"},
        }
        admin = RuntimeProviderOperationalWarningResponse.from_dict(admin_payload)
        assert admin is not None
        self.assertEqual(admin.to_dict(), admin_payload)
        self.assertEqual(
            AdminApiClient().sanitize_for_serialization(admin), admin_payload
        )


if __name__ == "__main__":
    unittest.main()
