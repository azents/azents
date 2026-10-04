"""Nested owned input strictness and opaque SDK credential field contracts."""

import pytest
from pydantic import BaseModel, ValidationError

from azents.engine.tools.external_channel import ChannelActionInput
from azents.engine.tools.import_file import ImportFileInput
from azents.engine.tools.kubernetes_auth import (
    EksCredential,
    GkeCredential,
    KubeconfigCredential,
    KubernetesCredentials,
    TokenCredential,
)
from azents.engine.tools.scheduled import AddScheduledTaskInput


@pytest.mark.parametrize("level", ["task", "source"])
def test_channel_nested_unknown_fields_are_rejected(level: str) -> None:
    """Owned nested task/source payloads cannot silently discard a typo."""
    source: dict[str, object] = {"url": "https://example.test", "label": "Source"}
    task: dict[str, object] = {
        "id": "task-1",
        "title": "Task",
        "status": "pending",
        "sources": [source],
    }
    (task if level == "task" else source)["undeclared"] = "value"
    with pytest.raises(ValidationError, match="extra_forbidden") as caught:
        ChannelActionInput.model_validate(
            {
                "mode": "finish",
                "binding": "active",
                "message": "Done",
                "todo_update": [task],
            }
        )
    expected_location = (
        ("todo_update", 0, "undeclared")
        if level == "task"
        else ("todo_update", 0, "sources", 0, "undeclared")
    )
    assert caught.value.errors()[0]["loc"] == expected_location


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (KubeconfigCredential, {"kubeconfig_yaml": "opaque: future"}),
        (TokenCredential, {"token": "token", "ca_cert": None}),
        (
            EksCredential,
            {"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        ),
        (
            GkeCredential,
            {"service_account_key": {"future_sdk_field": {"opaque": True}}},
        ),
        (KubernetesCredentials, {"clusters": {}}),
    ],
)
def test_owned_credential_envelopes_reject_unknown_fields(
    model: type[BaseModel], payload: dict[str, object]
) -> None:
    """Reject envelope typos without applying strictness inside provider documents."""
    validated = model.model_validate(payload)
    assert validated.model_dump(exclude_unset=True) == payload
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate({**payload, "undeclared": "value"})


def test_nested_credential_rejection_preserves_sdk_opaque_fields() -> None:
    """Container validates each owned variant but permits extensible SDK data."""
    sdk_fields = {"client_email": "a@example.test", "future_sdk_field": {"raw": 1}}
    credentials = KubernetesCredentials.model_validate(
        {"clusters": {"home": {"type": "gke", "service_account_key": sdk_fields}}}
    )
    cluster = credentials.clusters["home"]
    assert isinstance(cluster, GkeCredential)
    assert cluster.service_account_key == sdk_fields
    with pytest.raises(ValidationError, match="extra_forbidden"):
        KubernetesCredentials.model_validate(
            {"clusters": {"home": {"type": "token", "token": "x", "typo": True}}}
        )


def test_existing_null_default_and_whitespace_semantics_remain_explicit() -> None:
    """Strict unknown policy does not change existing value/presence contracts."""
    omitted = ImportFileInput(uri="exchange://object")
    explicit = ImportFileInput(uri="exchange://object", path=None)
    assert omitted.path is explicit.path is None
    assert "path" not in omitted.model_fields_set
    assert "path" in explicit.model_fields_set
    assert omitted.overwrite is explicit.overwrite is False
    schedule = AddScheduledTaskInput(
        title=" Inspect ",
        objective=" Objective ",
        at=None,
        cron="0 * * * *",
        timezone="UTC",
        channel_id=None,
    )
    assert schedule.title == "Inspect"
    assert schedule.objective == "Objective"
    assert schedule.at is None
    assert schedule.channel_id is None
