"""Credential and GKE operations exercise public SDK factory/transport boundaries."""

import asyncio
import datetime
import json
from collections.abc import Mapping
from dataclasses import dataclass
from unittest.mock import MagicMock, create_autospec, patch
from urllib.parse import parse_qs

import google.auth.jwt
import google.auth.transport
import google.auth.transport.requests
import pytest
import requests
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.api_core.client_options import ClientOptions
from google.auth.exceptions import RefreshError
from google.cloud import container_v1
from google.oauth2 import service_account

from azents.engine.tools.aws import AwsCredentialProvider
from azents.engine.tools.gcp import (
    GcpAccessTokenProvider,
    GoogleAuthDispatchBudgetExceeded,
)
from azents.engine.tools.kubernetes_auth import (
    GkeCredential,
    _get_gke_cluster_info,
    _scan_gke_clusters_sync,
)


@pytest.mark.parametrize("external_id", [None, "external-1"])
async def test_actual_aws_credential_factory_uses_public_sts_and_cache(
    external_id: str | None,
) -> None:
    """Session identity, role arguments, endpoint, timeout and cache stay explicit."""
    session = MagicMock(spec=["client"])
    client = MagicMock(spec=["assume_role", "close"])
    session.client.return_value = client
    client.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "assumed-key",
            "SecretAccessKey": "assumed-secret",
            "SessionToken": "assumed-token",
            "Expiration": datetime.datetime.now(datetime.UTC),
        },
        "FutureSDKMetadata": {"opaque": True},
    }
    provider = AwsCredentialProvider(
        "source-key",
        "source-secret",
        "eu-west-1",
        role_arn="arn:aws:iam::123456789012:role/test",
        external_id=external_id,
    )
    with patch(
        "azents.engine.tools.aws.boto3.Session", return_value=session
    ) as factory:
        first, second = await asyncio.gather(
            provider.get_credentials(), provider.get_credentials()
        )
    factory.assert_called_once_with(
        aws_access_key_id="source-key",
        aws_secret_access_key="source-secret",
        aws_session_token=None,
        region_name="eu-west-1",
    )
    kwargs = session.client.call_args.kwargs
    assert kwargs["region_name"] == "eu-west-1"
    assert kwargs["endpoint_url"] == "https://sts.eu-west-1.amazonaws.com/"
    assert kwargs["config"].connect_timeout == 30
    assert kwargs["config"].read_timeout == 30
    assert kwargs["config"].retries == {"total_max_attempts": 1}
    expected: dict[str, object] = {
        "RoleArn": "arn:aws:iam::123456789012:role/test",
        "RoleSessionName": "azents-aws-toolkit",
        "DurationSeconds": 3600,
    }
    if external_id is not None:
        expected["ExternalId"] = external_id
    client.assume_role.assert_called_once_with(**expected)
    client.close.assert_called_once()
    assert first is second
    assert first.access_key == "assumed-key"
    assert first.secret_key == "assumed-secret"
    assert first.token == "assumed-token"


async def test_sts_sdk_failure_closes_client_without_publishing_credentials() -> None:
    """Natural SDK failure is preserved; no failed attempt poisons the cache."""
    session = MagicMock(spec=["client"])
    client = MagicMock(spec=["assume_role", "close"])
    session.client.return_value = client
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "AssumeRole"
    )
    client.assume_role.side_effect = error
    provider = AwsCredentialProvider(
        "source-key",
        "source-secret",
        "us-east-1",
        role_arn="arn:aws:iam::123456789012:role/test",
    )
    with patch("azents.engine.tools.aws.boto3.Session", return_value=session):
        with pytest.raises(ClientError) as caught:
            await provider.get_credentials()
    assert caught.value is error
    client.close.assert_called_once()
    assert provider._assumed is None
    assert provider._assumed_expiry is None


async def test_direct_aws_credentials_do_not_create_an_sts_client() -> None:
    """The existing direct access-key lane remains local and unchanged."""
    provider = AwsCredentialProvider("direct", "secret", "us-east-1")
    with patch("azents.engine.tools.aws.boto3.Session") as factory:
        first = await provider.get_credentials()
        assert await provider.get_credentials() is first
    factory.assert_not_called()
    assert first.access_key == "direct"
    assert first.token is None


class _AuthResponse(google.auth.transport.Response):
    """Synthetic response at the SDK's public transport receipt boundary."""

    def __init__(self, status: int, data: bytes) -> None:
        self.code = status
        self.body = data

    @property
    def status(self) -> int:
        return self.code

    @property
    def data(self) -> bytes:
        return self.body

    @property
    def headers(self) -> Mapping[str, str]:
        return {"Content-Type": "application/json"}


@dataclass(frozen=True)
class _AuthCall:
    url: str
    method: str
    body: bytes | None
    timeout: float | None
    transport_options: dict[str, object]


class _AuthSession(requests.Session):
    """Real session state with observable public close ownership."""

    def __init__(self) -> None:
        super().__init__()
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        super().close()


class _AuthRequest(google.auth.transport.requests.Request):
    """Typed public transport fake, with the SDK session's closure observable."""

    def __init__(self, response: _AuthResponse) -> None:
        self.response = response
        self.calls: list[_AuthCall] = []
        self.owned_session = _AuthSession()
        self.session = self.owned_session

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> google.auth.transport.Response:
        del headers
        self.calls.append(
            _AuthCall(
                url=url,
                method=method,
                body=body,
                timeout=timeout,
                transport_options=dict(kwargs),
            )
        )
        return self.response


@pytest.fixture(scope="module")
def service_account_key() -> dict[str, str]:
    """Ephemeral signing key drives actual Google credential SDK signing/parsing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {
        "type": "service_account",
        "client_email": "test@example.test",
        "private_key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        "token_uri": "https://not-authority.example.test/token",
        "universe_domain": "not-authority.example.test",
        "private_key_id": "opaque-kid-not-adopted",
        "project_id": "project-1",
    }


async def test_actual_google_credential_sdk_signs_parses_and_caches(
    service_account_key: dict[str, str],
) -> None:
    """SDK owns assertion and receipt; existing endpoint/timeout/cache stay bounded."""
    request = _AuthRequest(
        _AuthResponse(
            200,
            json.dumps(
                {
                    "access_token": "sdk-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }
            ).encode(),
        )
    )
    provider = GcpAccessTokenProvider(service_account_key, ["scope-1", "scope-2"])
    with patch(
        "azents.engine.tools.gcp.google.auth.transport.requests.Request",
        return_value=request,
    ):
        first, second = await asyncio.gather(provider.get_token(), provider.get_token())
    assert first == second == "sdk-token"
    assert len(request.calls) == 1
    assert request.calls[0].url == "https://oauth2.googleapis.com/token"
    assert request.calls[0].method == "POST"
    assert request.calls[0].timeout == 30.0
    assert request.calls[0].transport_options["allow_redirects"] is False
    assert request.calls[0].body is not None
    assert b"assertion=" in request.calls[0].body
    assertion = parse_qs(request.calls[0].body.decode())["assertion"][0]
    claims = google.auth.jwt.decode(assertion, verify=False)
    header = google.auth.jwt.decode_header(assertion)
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert claims["iss"] == "test@example.test"
    assert claims["scope"] == "scope-1 scope-2"
    assert header["alg"] == "RS256"
    assert "kid" not in header
    assert request.owned_session.close_count == 1
    assert provider._expires_at is not None
    assert provider._expires_at.tzinfo is not None
    assert provider._expires_at.utcoffset() == datetime.timedelta(0)
    assert provider._expires_at > datetime.datetime.now(datetime.UTC)
    provider.invalidate()
    assert provider._token is provider._expires_at is None


async def test_google_sdk_eligible_failure_cannot_dispatch_again(
    service_account_key: dict[str, str],
) -> None:
    """A retryable SDK receipt hits the typed single-dispatch guard."""
    request = _AuthRequest(
        _AuthResponse(
            503,
            json.dumps(
                {
                    "error": "temporarily_unavailable",
                    "error_description": "retry later",
                }
            ).encode(),
        )
    )
    provider = GcpAccessTokenProvider(service_account_key, ["scope-1"])
    with patch(
        "azents.engine.tools.gcp.google.auth.transport.requests.Request",
        return_value=request,
    ):
        with pytest.raises(GoogleAuthDispatchBudgetExceeded) as caught:
            await provider.get_token()
    assert caught.value.status_code == 503
    assert caught.value.retryable is False
    assert len(request.calls) == 1
    assert provider._token is provider._expires_at is None
    assert request.owned_session.close_count == 1


async def test_google_nonretryable_error_keeps_sdk_exception(
    service_account_key: dict[str, str],
) -> None:
    """An ordinary invalid-grant response remains the natural SDK refresh failure."""
    request = _AuthRequest(_AuthResponse(400, b'{"error":"invalid_grant"}'))
    provider = GcpAccessTokenProvider(service_account_key, ["scope-1"])
    with patch(
        "azents.engine.tools.gcp.google.auth.transport.requests.Request",
        return_value=request,
    ):
        with pytest.raises(RefreshError, match="invalid_grant") as caught:
            await provider.get_token()
    assert not isinstance(caught.value, GoogleAuthDispatchBudgetExceeded)
    assert len(request.calls) == 1
    assert request.owned_session.close_count == 1


@pytest.mark.parametrize("malformed", [False, True])
def test_gke_get_uses_public_sdk_and_typed_cluster(malformed: bool) -> None:
    """Get identity/auth/REST/timeout are public SDK arguments, not manual HTTP."""
    credentials = create_autospec(service_account.Credentials, instance=True)
    client = create_autospec(container_v1.ClusterManagerClient, instance=True)
    client.__enter__.return_value = client
    client.get_cluster.return_value = container_v1.Cluster(
        endpoint="" if malformed else "192.0.2.10",
        master_auth=container_v1.MasterAuth(cluster_ca_certificate="encoded-ca"),
    )
    with patch(
        "azents.engine.tools.kubernetes_auth.container_v1.ClusterManagerClient",
        return_value=client,
    ) as factory:
        if malformed:
            with pytest.raises(ValueError, match="endpoint or CA"):
                _get_gke_cluster_info(credentials, "project-1", "cluster-1", "region-1")
        else:
            result = _get_gke_cluster_info(
                credentials, "project-1", "cluster-1", "region-1"
            )
            assert result.endpoint == "https://192.0.2.10"
            assert result.ca_cert_b64 == "encoded-ca"
    client.get_cluster.assert_called_once_with(
        name="projects/project-1/locations/region-1/clusters/cluster-1",
        retry=None,
        timeout=None,
    )
    kwargs = factory.call_args.kwargs
    assert kwargs["credentials"] is credentials
    assert kwargs["transport"] == "rest"
    options = kwargs["client_options"]
    assert isinstance(options, ClientOptions)
    assert options.api_endpoint == "container.googleapis.com"
    client.__exit__.assert_called_once()


def test_gke_scan_uses_sdk_all_location_list_and_preserves_display_fields() -> None:
    """Typed SDK clusters retain existing discovery name/location/status/versions."""
    credentials = create_autospec(service_account.Credentials, instance=True)
    client = create_autospec(container_v1.ClusterManagerClient, instance=True)
    client.__enter__.return_value = client
    client.list_clusters.return_value = container_v1.ListClustersResponse(
        clusters=[
            container_v1.Cluster(
                name="cluster-1",
                location="region-1",
                endpoint="192.0.2.1",
                current_master_version="1.36",
                status=container_v1.Cluster.Status.RUNNING,
            ),
            container_v1.Cluster(name="unknown"),
        ]
    )
    credential = GkeCredential(service_account_key={"future_sdk_field": True})
    with (
        patch(
            "azents.engine.tools.kubernetes_auth.service_account.Credentials.from_service_account_info",
            return_value=credentials,
        ),
        patch(
            "azents.engine.tools.kubernetes_auth.container_v1.ClusterManagerClient",
            return_value=client,
        ),
    ):
        result = _scan_gke_clusters_sync(credential, "project-1")
    client.list_clusters.assert_called_once_with(
        parent="projects/project-1/locations/-",
        retry=None,
        timeout=None,
    )
    assert result == [
        {
            "name": "cluster-1",
            "region": "region-1",
            "status": "RUNNING",
            "endpoint": "192.0.2.1",
            "version": "1.36",
        },
        {
            "name": "unknown",
            "region": "",
            "status": "UNKNOWN",
            "endpoint": "",
            "version": "",
        },
    ]
    client.__exit__.assert_called_once()
