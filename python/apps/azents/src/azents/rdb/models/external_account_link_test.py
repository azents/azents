"""External account link model contract tests."""

from azents.rdb.models.external_account_link import (
    RDBExternalAccountLink,
    RDBExternalAccountLinkCandidate,
    RDBExternalAccountLinkOrigin,
)


def test_link_model_has_active_partial_uniqueness_and_safe_labels() -> None:
    """Keep identity ownership keys separate from user-facing labels."""
    columns = set(RDBExternalAccountLink.__table__.columns.keys())
    assert columns == {
        "id",
        "workspace_id",
        "user_id",
        "provider",
        "identity_scope",
        "provider_user_id",
        "provider_tenant_display_label",
        "provider_display_label",
        "linked_at",
        "revoked_at",
    }
    indexes = (
        RDBExternalAccountLink.UQ_ACTIVE_EXTERNAL_IDENTITY,
        RDBExternalAccountLink.UQ_ACTIVE_USER_PROVIDER_SCOPE,
    )
    assert {index.name for index in indexes} == {
        "uq_external_account_links_active_external_identity",
        "uq_external_account_links_active_user_provider_scope",
    }
    assert all(
        str(index.dialect_options["postgresql"]["where"]) == "revoked_at IS NULL"
        for index in indexes
    )


def test_proof_models_persist_hash_only_and_lifecycle_cascades() -> None:
    """Keep plaintext proof and provider callback material outside persistence."""
    origin_columns = set(RDBExternalAccountLinkOrigin.__table__.columns.keys())
    candidate_columns = set(RDBExternalAccountLinkCandidate.__table__.columns.keys())
    assert "code" not in origin_columns | candidate_columns
    assert "callback" not in origin_columns | candidate_columns
    assert "raw_payload" not in origin_columns | candidate_columns
    assert "code_hash" in candidate_columns

    candidate_foreign_keys = {
        foreign_key.parent.name: foreign_key
        for foreign_key in RDBExternalAccountLinkCandidate.__table__.foreign_keys
    }
    assert candidate_foreign_keys["origin_id"].ondelete == "CASCADE"
    assert candidate_foreign_keys["user_id"].ondelete == "CASCADE"
    assert candidate_foreign_keys["auth_session_id"].ondelete == "CASCADE"
    assert candidate_foreign_keys["link_id"].ondelete == "SET NULL"
