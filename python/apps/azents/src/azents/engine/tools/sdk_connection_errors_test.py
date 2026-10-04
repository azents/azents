"""Expected authentication SDK errors retain the Toolkit connection-test contract."""

import json
from typing import Literal, assert_never
from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError
from google.auth.exceptions import RefreshError

from azents.core.tools import AwsToolkitConfig, GcpService, GcpToolkitConfig
from azents.engine.tools.aws import AwsCredentialProvider, AwsToolkitProvider
from azents.engine.tools.gcp import GcpAccessTokenProvider, GcpToolkitProvider


@pytest.mark.parametrize("kind", ["aws", "gcp"])
@pytest.mark.parametrize("expected", [False, True])
async def test_connection_sdk_auth_failure_and_unexpected_error_identity(
    kind: Literal["aws", "gcp"], expected: bool
) -> None:
    """A natural SDK auth failure is negative evidence, not an unexpected 500."""
    match kind:
        case "aws":
            error = (
                ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "secret-marker"}},
                    "AssumeRole",
                )
                if expected
                else ValueError("invariant")
            )
            config = AwsToolkitConfig(region="us-east-1")
            credentials = json.dumps(
                {
                    "access_key_id": "key",
                    "secret_access_key": "secret",
                }
            )
            with patch.object(
                AwsCredentialProvider, "get_credentials", AsyncMock(side_effect=error)
            ):
                if expected:
                    result = await AwsToolkitProvider().test_connection(
                        config, credentials
                    )
                else:
                    with pytest.raises(ValueError) as caught:
                        await AwsToolkitProvider().test_connection(config, credentials)
                    assert caught.value is error
                    return
        case "gcp":
            error = (
                RefreshError("secret-marker") if expected else ValueError("invariant")
            )
            config = GcpToolkitConfig(
                project_id="project-1", services=[GcpService.LOGGING]
            )
            credentials = json.dumps(
                {
                    "service_account_key": {
                        "client_email": "test@example.test",
                        "private_key": "unused",
                    }
                }
            )
            with patch.object(
                GcpAccessTokenProvider, "get_token", AsyncMock(side_effect=error)
            ):
                if expected:
                    result = await GcpToolkitProvider().test_connection(
                        config, credentials
                    )
                else:
                    with pytest.raises(ValueError) as caught:
                        await GcpToolkitProvider().test_connection(config, credentials)
                    assert caught.value is error
                    return
        case _ as unreachable:
            assert_never(unreachable)
    assert result.success is False
    assert "Authentication failed" in result.message
    assert "secret-marker" not in result.message
