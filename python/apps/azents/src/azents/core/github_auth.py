"""GitHub App authentication utilities.

Logic for GitHub App JWT creation and Installation Access Token exchange.
"""

import logging
import time

import httpx
import jwt

logger = logging.getLogger(__name__)


def create_github_app_jwt(app_id: str, private_key: str) -> str:
    """Create GitHub App JWT with RS256, 9-minute expiry, and 60-second backdate.

    :param app_id: GitHub App ID
    :param private_key: Private key in PEM format
    :return: JWT string
    """
    # Convert because literal ``\\n`` can remain from environment variables
    normalized_key = private_key.replace("\\n", "\n")
    now = int(time.time())
    payload = {
        "iat": now - 60,  # 60-second backdate for clock skew tolerance
        "exp": now + (9 * 60),  # 9-minute expiry, max 10 minutes
        "iss": app_id,
    }
    return jwt.encode(payload, normalized_key, algorithm="RS256")


async def get_app_slug(jwt_token: str) -> str:
    """Get GitHub App slug.

    GitHub API ``GET /app`` call.

    :param jwt_token: GitHub App JWT
    :return: App slug (e.g. ``my-github-app``)
    :raises httpx.HTTPStatusError: GitHub API call failure
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/app",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        data: dict[str, object] = response.json()
        slug = data["slug"]
        assert isinstance(slug, str)  # noqa: S101 — GitHub API response schema guarantee
        return slug


async def exchange_oauth_code(
    client_id: str,
    client_secret: str,
    code: str,
) -> str:
    """Exchange GitHub OAuth authorization code for access token.

    :param client_id: OAuth Client ID
    :param client_secret: OAuth Client Secret
    :param code: Authorization code
    :return: Access token
    :raises httpx.HTTPStatusError: GitHub API call failure
    :raises ValueError: When access_token is missing from response
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
        )
        response.raise_for_status()
        data: dict[str, object] = response.json()
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            error = data.get("error", "unknown_error")
            desc = data.get("error_description", "")
            msg = f"OAuth token exchange failed: {error}"
            if desc:
                msg += f" - {desc}"
            raise ValueError(msg)
        return token


async def list_user_installations(
    user_token: str,
) -> list[dict[str, object]]:
    """List GitHub App installations accessible by authenticated user.

    GitHub API ``GET /user/installations`` call.
    Uses the user OAuth token, so only installations accessible by that user are
    returned.

    :param user_token: User GitHub access token
    :return: Installation list; each item includes id, account, app_id, etc.
    :raises httpx.HTTPStatusError: GitHub API call failure
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/installations",
            headers={
                "Authorization": f"Bearer {user_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"per_page": 100},
        )
        response.raise_for_status()
        data: dict[str, object] = response.json()
        installations = data.get("installations")
        if not isinstance(installations, list):
            return []
        return installations


async def list_installations(jwt_token: str) -> list[dict[str, object]]:
    """List all installations of the GitHub App.

    GitHub API ``GET /app/installations`` call.
    Uses App JWT, so returns all installations for that App.

    :param jwt_token: GitHub App JWT
    :return: Installation list; each item includes id, account, app_id, etc.
    :raises httpx.HTTPStatusError: GitHub API call failure
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/app/installations",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"per_page": 100},
        )
        response.raise_for_status()
        data: object = response.json()
        if not isinstance(data, list):
            return []
        return data


async def revoke_oauth_token(
    client_id: str,
    client_secret: str,
    token: str,
) -> None:
    """Revoke GitHub OAuth token.

    Immediately invalidates used temporary tokens to reduce token leak risk.
    On failure, logs only a warning and does not propagate exceptions.

    :param client_id: OAuth Client ID
    :param client_secret: OAuth Client Secret
    :param token: Access token to revoke
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                "DELETE",
                f"https://api.github.com/applications/{client_id}/token",
                auth=(client_id, client_secret),
                json={"access_token": token},
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to revoke GitHub OAuth token",
            exc_info=True,
        )


async def get_installation(jwt_token: str, installation_id: str) -> dict[str, object]:
    """Fetch GitHub App installation metadata.

    :param jwt_token: GitHub App JWT
    :param installation_id: Installation ID
    :return: GitHub installation JSON object
    :raises httpx.HTTPStatusError: GitHub API call failure
    """
    url = f"https://api.github.com/app/installations/{installation_id}"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        data: object = response.json()
        if not isinstance(data, dict):
            return {}
        return data


async def exchange_installation_token(jwt_token: str, installation_id: str) -> str:
    """Exchange JWT for Installation Access Token.

    GitHub API ``POST /app/installations/{id}/access_tokens`` call.

    :param jwt_token: GitHub App JWT
    :param installation_id: Installation ID
    :return: Installation access token (``ghs_...``)
    :raises httpx.HTTPStatusError: GitHub API call failure
    """
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        data: dict[str, object] = response.json()
        token = data["token"]
        assert isinstance(token, str)  # noqa: S101 — GitHub API response schema guarantee
        return token
