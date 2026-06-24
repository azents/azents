"""GitHub PAT service unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from azents.services.github_pat import GitHubPATService


def _make_service() -> GitHubPATService:
    """Create a service for tests without DI."""
    service = GitHubPATService.__new__(GitHubPATService)
    mock_config = MagicMock()
    mock_config.mcp_proxy_url = None
    service.config = mock_config
    service.pat_repo = MagicMock()
    service.session_manager = AsyncMock()
    return service


class TestVerifyToken:
    """GitHub token validation tests."""

    @pytest.mark.asyncio
    async def test_valid_token(self) -> None:
        """Return GitHub username for a valid token."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "octocat"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        target = "azents.services.github_pat.httpx.AsyncClient"
        with patch(target) as patched:
            patched.return_value.__aenter__.return_value = mock_client
            service = _make_service()
            result = await service._verify_token("example-valid-token")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert result == "octocat"

    @pytest.mark.asyncio
    async def test_invalid_token(self) -> None:
        """Return None for an invalid token."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        target = "azents.services.github_pat.httpx.AsyncClient"
        with patch(target) as patched:
            patched.return_value.__aenter__.return_value = mock_client
            service = _make_service()
            result = await service._verify_token("example-bad-token")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert result is None

    @pytest.mark.asyncio
    async def test_network_error(self) -> None:
        """Return None on network errors."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        target = "azents.services.github_pat.httpx.AsyncClient"
        with patch(target) as patched:
            patched.return_value.__aenter__.return_value = mock_client
            service = _make_service()
            result = await service._verify_token("example-any-token")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert result is None

    @pytest.mark.asyncio
    async def test_proxy_url_passed(self) -> None:
        """Pass proxy URL to httpx.AsyncClient when configured."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "octocat"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        target = "azents.services.github_pat.httpx.AsyncClient"
        with patch(target) as patched:
            patched.return_value.__aenter__.return_value = mock_client
            service = _make_service()
            service.config.mcp_proxy_url = "http://proxy:8080"
            await service._verify_token("example-test-token")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
            patched.assert_called_once_with(proxy="http://proxy:8080")
