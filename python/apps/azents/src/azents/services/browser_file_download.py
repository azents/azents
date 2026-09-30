"""Request-local capabilities for authorized browser file downloads."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

BROWSER_DOWNLOAD_TICKET_TTL = timedelta(minutes=1)
INLINE_IMAGE_MEDIA_TYPES = frozenset(
    {"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"}
)


@dataclass(frozen=True)
class BrowserFileDownloadTicket:
    """Ephemeral GET capability; issuance does not observe browser completion."""

    url: str = field(repr=False)
    expires_at: datetime
