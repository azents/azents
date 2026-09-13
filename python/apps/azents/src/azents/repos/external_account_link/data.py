"""Detached data for external account link persistence."""

import dataclasses
import datetime

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkRevocationReason,
)


@dataclasses.dataclass(frozen=True)
class ExternalAccountLink:
    """Persisted global external account link."""

    id: str
    user_id: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_user_id: str
    provider_tenant_display_label: str | None
    provider_display_label: str
    linked_at: datetime.datetime
    revoked_at: datetime.datetime | None
    legacy_workspace_id: str | None
    revocation_reason: ExternalAccountLinkRevocationReason | None

    @property
    def workspace_id(self) -> str | None:
        """Return retained legacy workspace provenance."""
        return self.legacy_workspace_id
