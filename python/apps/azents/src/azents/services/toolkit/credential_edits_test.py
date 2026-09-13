"""Tests for redacted Toolkit credential editing."""

from azents.services.toolkit.credential_edits import (
    merge_kubernetes_credentials,
    merge_redacted_credential_values,
)


def test_redacted_merge_preserves_blank_nested_values() -> None:
    """Blank nested inputs keep the stored credential value."""
    assert merge_redacted_credential_values(
        {
            "type": "token",
            "token": "stored-token",
            "ca_cert": "stored-ca",
        },
        {
            "type": "token",
            "token": "",
            "ca_cert": None,
        },
    ) == {
        "type": "token",
        "token": "stored-token",
        "ca_cert": "stored-ca",
    }


def test_kubernetes_merge_preserves_untouched_clusters() -> None:
    """Replacing one cluster does not remove another stored cluster."""
    merged = merge_kubernetes_credentials(
        (
            '{"clusters":{'
            '"production":{"type":"kubeconfig","kubeconfig_yaml":"stored-yaml"},'
            '"staging":{"type":"token","token":"stored-token","ca_cert":"stored-ca"}'
            "}}"
        ),
        {
            "clusters": {
                "production": {
                    "type": "kubeconfig",
                    "kubeconfig_yaml": "replacement-yaml",
                }
            }
        },
        {
            "clusters": [
                {"name": "production", "auth_type": "kubeconfig"},
                {"name": "staging", "auth_type": "token"},
            ]
        },
    )

    assert merged == {
        "clusters": {
            "production": {
                "type": "kubeconfig",
                "kubeconfig_yaml": "replacement-yaml",
            },
            "staging": {
                "type": "token",
                "token": "stored-token",
                "ca_cert": "stored-ca",
            },
        }
    }


def test_kubernetes_merge_prunes_removed_cluster() -> None:
    """A cluster removed from config also loses its stored credential."""
    merged = merge_kubernetes_credentials(
        (
            '{"clusters":{'
            '"production":{"type":"kubeconfig","kubeconfig_yaml":"stored-yaml"},'
            '"removed":{"type":"token","token":"stored-token"}'
            "}}"
        ),
        None,
        {
            "clusters": [
                {"name": "production", "auth_type": "kubeconfig"},
            ]
        },
    )

    assert merged == {
        "clusters": {
            "production": {
                "type": "kubeconfig",
                "kubeconfig_yaml": "stored-yaml",
            }
        }
    }


def test_kubernetes_auth_change_does_not_reuse_incompatible_secret() -> None:
    """Changing authentication method starts an unpopulated credential object."""
    merged = merge_kubernetes_credentials(
        '{"clusters":{"production":{"type":"token","token":"stored-token"}}}',
        None,
        {
            "clusters": [
                {"name": "production", "auth_type": "kubeconfig"},
            ]
        },
    )

    assert merged == {
        "clusters": {
            "production": {
                "type": "kubeconfig",
            }
        }
    }
