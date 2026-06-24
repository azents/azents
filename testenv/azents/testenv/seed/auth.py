"""Auth seeding helpers.

`Auth` is constructed with `TestenvConfig` and exposes `create_user()`. It
reuses the three-step flow from the E2E `authenticate_user` helper:
    1. Public `auth/v1/email/send-code` → csrf_token
    2. Admin `auth/v1/email-verifications/by-email` → code peek
    3. Public `auth/v1/email/verify` → access/refresh token

The testenv devserver allows internal admin API access without a token
(Discussion §3.7, Phase 3 feasibility verified).

Normally use this through `TestenvClient.auth`.
"""

from dataclasses import dataclass

from azentsadminclient.api.auth_v1_api import AuthV1Api as AdminAuthV1Api
from azentspublicclient.api.auth_v1_api import AuthV1Api as PublicAuthV1Api
from azentspublicclient.models.send_code_request import SendCodeRequest
from azentspublicclient.models.verify_code_request import VerifyCodeRequest

from testenv.runtime_config import TestenvConfig

from .client import admin_client, public_client
from .types import User
from .unique import unique


@dataclass(frozen=True)
class Auth:
    """Auth seed service used by `TestenvClient.auth`."""

    config: TestenvConfig

    def create_user(self, email: str | None = None) -> User:
        """Create a user through email auth and return issued tokens.

        When email is None, create `test-{unique()}@example.com`.
        """
        if email is None:
            email = f"test-{unique()}@example.com"

        pub = PublicAuthV1Api(public_client(self.config))
        adm = AdminAuthV1Api(admin_client(self.config))

        send = pub.auth_v1_send_code(SendCodeRequest(email=email))
        csrf_token = send.csrf_token

        verification = adm.auth_v1_get_email_verification_by_email(
            email=email,
            csrf_token=csrf_token,
        )

        verify = pub.auth_v1_verify_code(
            VerifyCodeRequest(email=email, code=verification.code, csrf_token=csrf_token),
        )

        return User(
            email=email,
            access_token=verify.access_token,
            refresh_token=verify.refresh_token,
        )
