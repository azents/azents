"""External account link model contract tests."""

from azents.rdb.models.external_account_link import RDBExternalAccountLink


def test_link_model_has_active_partial_uniqueness_and_safe_labels() -> None:
    """Keep identity ownership keys separate from user-facing labels."""
    columns = set(RDBExternalAccountLink.__table__.columns.keys())
    assert columns == {
        "id",
        "legacy_workspace_id",
        "user_id",
        "provider",
        "identity_scope",
        "provider_user_id",
        "provider_tenant_display_label",
        "provider_display_label",
        "linked_at",
        "revoked_at",
        "revocation_reason",
    }
    indexes = (RDBExternalAccountLink.UQ_ACTIVE_EXTERNAL_IDENTITY,)
    assert {index.name for index in indexes} == {
        "uq_external_account_links_active_external_identity",
    }
    assert all(
        str(index.dialect_options["postgresql"]["where"]) == "revoked_at IS NULL"
        for index in indexes
    )
