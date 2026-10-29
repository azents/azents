"""Nested Google call credentials cannot hide management tokens or endpoints."""

import json

import pytest
from pydantic import SecretStr, ValidationError

from azents_llm_contract.authority import VertexCredential
from azents_llm_contract.gcp import ServiceAccountKey, service_account_call_json

SENTINEL = "private-key-sentinel"


def key() -> dict[str, object]:
    return {
        "type": "service_account",
        "private_key": SENTINEL,
        "client_email": "fixture@example.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def test_call_material_preserves_key_but_omits_unused_management_metadata() -> None:
    source = {
        **key(),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "client_id": "display-only",
        "client_x509_cert_url": "https://example.invalid/cert",
    }
    material = ServiceAccountKey.model_validate(source)
    assert SENTINEL not in repr(material)
    assert SENTINEL not in material.model_dump_json()
    actual = json.loads(service_account_call_json(json.dumps(source)))
    assert actual == key()
    assert "auth_uri" not in actual and "client_x509_cert_url" not in actual


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "authorized_user", "refresh_token": "refresh-sentinel"},
        {
            "type": "external_account",
            "credential_source": {"executable": {"command": "command-sentinel"}},
        },
        {"refresh_token": "refresh-sentinel"},
        {"unrecognized_sdk_argument": "unknown-sentinel"},
        {"token_uri": "http://control.internal/token"},
        {"token_uri": "https://control.internal/token"},
        {"universe_domain": "control.internal"},
    ],
)
def test_nested_management_and_endpoint_controls_fail_closed(
    changes: dict[str, object],
) -> None:
    document = json.dumps({**key(), **changes})
    with pytest.raises(ValidationError) as caught:
        VertexCredential(
            kind="google_vertex_ai",
            service_account_json=SecretStr(document),
            project_id="project",
            location="region",
        )
    assert SENTINEL not in str(caught.value)
    assert "refresh-sentinel" not in str(caught.value)
    assert "command-sentinel" not in str(caught.value)


def test_private_response_roundtrip_is_stable_and_redacted_by_default() -> None:
    value = VertexCredential(
        kind="google_vertex_ai",
        service_account_json=SecretStr(json.dumps(key())),
        project_id="project",
        location="region",
    )
    assert SENTINEL not in value.model_dump_json()
    wire = value.protected_json()
    assert SENTINEL in wire
    assert VertexCredential.model_validate_json(wire) == value
