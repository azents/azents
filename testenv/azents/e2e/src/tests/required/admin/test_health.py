"""Admin API Healthcheck test."""

import requests


class TestAdminHealth:
    """Admin API t t test."""

    def test_readiness(self, azents_admin_server_url: str) -> None:
        """Admin server readiness t."""
        response = requests.get(
            f"{azents_admin_server_url}/health/v1/readiness", timeout=5
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_liveness(self, azents_admin_server_url: str) -> None:
        """Admin server liveness t."""
        response = requests.get(
            f"{azents_admin_server_url}/health/v1/liveness", timeout=5
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
