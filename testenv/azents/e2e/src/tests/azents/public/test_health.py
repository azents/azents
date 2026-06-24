"""Public API Healthcheck test."""

import azentspublicclient
from azentspublicclient.api.health_v1_api import HealthV1Api


class TestPublicHealth:
    """Public API t t test."""

    def test_readiness(self, public_api_client: azentspublicclient.ApiClient) -> None:
        """Public server readiness t."""
        api = HealthV1Api(public_api_client)
        result = api.health_v1_readiness()
        assert result.status == "ok"

    def test_liveness(self, public_api_client: azentspublicclient.ApiClient) -> None:
        """Public server liveness t."""
        api = HealthV1Api(public_api_client)
        result = api.health_v1_liveness()
        assert result.status == "ok"
