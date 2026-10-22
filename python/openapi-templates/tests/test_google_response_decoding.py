"""Decode concrete Google API responses through regenerated native clients."""

import unittest

from azentsadminclient.models.google_application_detail import GoogleApplicationDetail
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
from azentspublicclient.models.google_preparation import GooglePreparation
from azentspublicclient.models.google_review import GoogleReview

_NO_DRIVE = {
    "whole_content_read": False,
    "whole_content_write": False,
    "whole_metadata_read": False,
    "whole_metadata_write": False,
    "app_file_read": False,
    "app_file_write": False,
}


class GoogleResponseDecodingTests(unittest.TestCase):
    def test_public_preparation_boolean_evidence(self) -> None:
        decoded = GooglePreparation.from_dict(
            {
                "status": "configured_unverified",
                "client_id": "test-client",
                "callback_url": "https://app.example.invalid/oauth/google/callback",
                "picker_status": "not_configured",
                "tool_group_catalog": [],
                "service_access_verified": False,
            }
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual(decoded.picker_status, "not_configured")
        self.assertIs(decoded.service_access_verified, False)

    def test_admin_preparation_boolean_evidence(self) -> None:
        decoded = GoogleApplicationDetail.from_dict(
            {
                "status": "configured_unverified",
                "client_id": "test-client",
                "callback_url": "https://app.example.invalid/oauth/google/callback",
                "picker_status": "not_configured",
                "tool_group_catalog": [],
                "service_access_verified": False,
                "section": "google_oauth",
                "schema_version": 1,
                "admin_version": 0,
                "client_id_source": "admin",
                "client_secret_source": "admin",
                "client_secret_configured": True,
                "picker_api_key": None,
                "picker_app_id": None,
                "picker_api_key_source": "unset",
                "picker_app_id_source": "unset",
            }
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual(decoded.picker_status, "not_configured")
        self.assertIs(decoded.service_access_verified, False)

    def test_public_partial_review_boolean_evidence(self) -> None:
        decoded = GoogleReview.from_dict(
            {
                "attempt_id": "attempt",
                "expires_at": "2026-10-14T00:00:00Z",
                "identity": {
                    "issuer": "https://accounts.google.com",
                    "subject": "subject",
                    "email": "test@example.invalid",
                },
                "client_id": "test-client",
                "ownership": "workspace_shared",
                "reconnect_toolkit_id": None,
                "services": ["calendar"],
                "tool_groups": ["calendar_read"],
                "oauth_request_scopes": ["openid", "email"],
                "granted_scopes": [
                    "https://www.googleapis.com/auth/calendar.events.readonly"
                ],
                "drive_access": _NO_DRIVE,
                "timeout": 30.0,
                "accesses": [
                    {
                        "service": "calendar",
                        "enabled": True,
                        "status": "partial",
                        "permitted_tools": ["calendar_list_events"],
                        "unavailable_tools": ["calendar_list_calendars"],
                    }
                ],
                "grant_result": "partial",
                "renewable": True,
                "can_confirm": True,
                "service_access_verified": False,
            }
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertIs(decoded.service_access_verified, False)
        self.assertTrue(decoded.can_confirm)

    def test_public_disconnected_state_boolean_evidence(self) -> None:
        decoded = GoogleConnectionOutput.from_dict(
            {
                "toolkit_id": "toolkit",
                "revision": 3,
                "connection_id": None,
                "status": "not_connected",
                "identity": None,
                "services": [],
                "tool_groups": [],
                "oauth_request_scopes": ["openid", "email"],
                "granted_scopes": None,
                "drive_access": _NO_DRIVE,
                "timeout": 30.0,
                "accesses": [],
                "renewable": False,
                "service_access_verified": False,
            }
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertIs(decoded.service_access_verified, False)
        self.assertIsNone(decoded.identity)
