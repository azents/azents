"""Decode concrete Google API responses through regenerated native clients."""

import unittest

from azentsadminclient.models.google_application_detail import GoogleApplicationDetail
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
from azentspublicclient.models.google_preparation import GooglePreparation
from azentspublicclient.models.google_review import GoogleReview


class GoogleResponseDecodingTests(unittest.TestCase):
    def test_public_preparation_boolean_evidence(self) -> None:
        decoded = GooglePreparation.from_dict(
            {
                "status": "configured_unverified",
                "client_id": "test-client",
                "callback_url": "https://app.example.invalid/oauth/google/callback",
                "preview_verified": False,
                "service_access_verified": False,
            }
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertIs(decoded.preview_verified, False)
        self.assertIs(decoded.service_access_verified, False)

    def test_admin_preparation_boolean_evidence(self) -> None:
        decoded = GoogleApplicationDetail.from_dict(
            {
                "status": "configured_unverified",
                "client_id": "test-client",
                "callback_url": "https://app.example.invalid/oauth/google/callback",
                "preview_verified": False,
                "service_access_verified": False,
                "section": "google_oauth",
                "schema_version": 1,
                "admin_version": 0,
                "client_id_source": "admin",
                "client_secret_source": "admin",
                "client_secret_configured": True,
            }
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertIs(decoded.preview_verified, False)
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
                "requested_tasks": ["calendar_read"],
                "timeout": 30.0,
                "tasks": [
                    {
                        "task": "calendar_read",
                        "service": "calendar",
                        "status": "partial",
                        "permitted_tools": ["list_events"],
                        "unavailable_tools": ["list_calendars"],
                    }
                ],
                "grant_result": "partial",
                "renewable": True,
                "can_confirm": True,
                "service_access_verified": False,
                "security_notice": "Known-pattern limits.",
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
                "status": "not_connected",
                "identity": None,
                "selected_tasks": ["calendar_read"],
                "timeout": 30.0,
                "tasks": [],
                "renewable": False,
                "service_access_verified": False,
            }
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertIs(decoded.service_access_verified, False)
        self.assertIsNone(decoded.identity)
