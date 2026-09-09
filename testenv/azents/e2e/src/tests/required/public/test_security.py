"""Public Security API E2E tests.

Verify password management, step-up authentication, and login.
"""

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.auth_v1_api import AuthV1Api as AdminAuthV1Api
from azentspublicclient.api.auth_v1_api import AuthV1Api as PublicAuthV1Api
from azentspublicclient.api.security_v1_api import SecurityV1Api
from azentspublicclient.models.elevate_with_email_request import (
    ElevateWithEmailRequest,
)
from azentspublicclient.models.elevate_with_password_request import (
    ElevateWithPasswordRequest,
)
from azentspublicclient.models.login_methods_response import LoginMethodsResponse
from azentspublicclient.models.password_login_request import PasswordLoginRequest
from azentspublicclient.models.refresh_token_request import RefreshTokenRequest
from azentspublicclient.models.set_password_request import SetPasswordRequest

from support.utils import authenticate_user, unique


def _elevate_user(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    access_token: str,
    email: str,
) -> str:
    """Elevate with an email OTP and return the elevated access token."""
    security_api = SecurityV1Api(public_api_client)
    adm_auth = AdminAuthV1Api(admin_api_client)

    # Request an elevation code.
    send_response = security_api.security_v1_send_elevation_code(
        _headers={"Authorization": f"Bearer {access_token}"},
    )
    csrf_token = send_response.csrf_token

    # Fetch the test verification code through the Admin API.
    verification = adm_auth.auth_v1_get_email_verification_by_email(
        email=email, csrf_token=csrf_token
    )

    # Elevate with the email verification code.
    elevate_response = security_api.security_v1_elevate_with_email(
        ElevateWithEmailRequest(code=verification.code, csrf_token=csrf_token),
        _headers={"Authorization": f"Bearer {access_token}"},
    )
    return elevate_response.access_token


class TestSecurityElevation:
    """Test step-up authentication."""

    def test_get_auth_methods_without_elevation_returns_403(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Fetching auth methods without elevation returns 403."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        security_api = SecurityV1Api(public_api_client)

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_get_auth_methods(
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 403

    def test_elevate_with_email_and_get_auth_methods(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Email OTP elevation allows fetching auth methods."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)

        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Fetch auth methods with the elevated token.
        security_api = SecurityV1Api(public_api_client)
        response = security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )
        assert response.methods is not None
        assert len(response.methods) > 0

        # The SMTP-disabled fixture leaves the email method unavailable.
        email_methods = [m for m in response.methods if m.type == "email"]
        assert len(email_methods) == 1
        assert email_methods[0].configured is True
        assert email_methods[0].enabled is False
        assert email_methods[0].valid is False
        assert email_methods[0].unavailable_reason == "smtp_not_configured"

    def test_elevate_with_wrong_code_returns_400(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Elevation with an incorrect code returns 400."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        security_api = SecurityV1Api(public_api_client)

        send_response = security_api.security_v1_send_elevation_code(
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_elevate_with_email(
                ElevateWithEmailRequest(
                    code="WRONG1",
                    csrf_token=send_response.csrf_token,
                ),
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 400

    def test_elevation_stripped_on_refresh(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Refreshing an access token removes elevation."""
        access_token, refresh_token, email = authenticate_user(
            public_api_client, admin_api_client
        )

        # Elevate the original access token.
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Verify that the elevated token reaches a protected endpoint.
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # Refresh the session to obtain a non-elevated access token.
        pub_auth = PublicAuthV1Api(public_api_client)
        refresh_response = pub_auth.auth_v1_refresh_token(
            RefreshTokenRequest(refresh_token=refresh_token)
        )
        new_access_token = refresh_response.access_token

        # The refreshed token must not retain elevation.
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_get_auth_methods(
                _headers={"Authorization": f"Bearer {new_access_token}"},
            )
        assert exc_info.value.status == 403


class TestPasswordManagement:
    """Test password management."""

    def test_set_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """An elevated user can set a password."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        security_api = SecurityV1Api(public_api_client)
        # The endpoint returns 204 No Content on success.
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # Verify that password authentication is enabled.
        response = security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )
        password_methods = [m for m in response.methods if m.type == "password"]
        assert len(password_methods) == 1
        assert password_methods[0].enabled is True

    def test_set_password_without_elevation_returns_403(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Setting a password without elevation returns 403."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        security_api = SecurityV1Api(public_api_client)

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_set_password(
                SetPasswordRequest(password="StrongP@ss1!"),
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 403

    def test_remove_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Removing the only valid credential is rejected."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        security_api = SecurityV1Api(public_api_client)

        # Set the password.
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # The SMTP-disabled fixture prevents deleting the only valid credential.
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_remove_password(
                _headers={"Authorization": f"Bearer {elevated_token}"},
            )
        assert exc_info.value.status == 409

        # Verify that the password credential remains enabled.
        response = security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )
        password_methods = [m for m in response.methods if m.type == "password"]
        assert len(password_methods) == 1
        assert password_methods[0].enabled is True

    def test_remove_initial_signup_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Removing the initial signup password is rejected."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        security_api = SecurityV1Api(public_api_client)
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_remove_password(
                _headers={"Authorization": f"Bearer {elevated_token}"},
            )
        assert exc_info.value.status == 409

        response = security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )
        password_methods = [m for m in response.methods if m.type == "password"]
        assert len(password_methods) == 1
        assert password_methods[0].enabled is True

    def test_elevate_with_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """A configured password can elevate a new session."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Set the password.
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # Authenticate a new session for password elevation.
        access_token_2, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=email
        )

        # Elevate with the configured password.
        elevate_response = security_api.security_v1_elevate_with_password(
            ElevateWithPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {access_token_2}"},
        )
        assert elevate_response.access_token is not None
        assert elevate_response.expires_in > 0

        # Verify that the elevated token reaches a protected endpoint.
        security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevate_response.access_token}"},
        )

    def test_elevate_with_wrong_password_returns_400(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Elevation with an incorrect password returns 400."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Set the password.
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # Attempt elevation with the wrong password.
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_elevate_with_password(
                ElevateWithPasswordRequest(password="WrongPassword!"),
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 400


class TestPasswordLogin:
    """Test password login."""

    def test_login_methods_after_signup_token_redeem_has_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Signup token redemption leaves password login enabled."""
        _, _, email = authenticate_user(public_api_client, admin_api_client)
        pub_auth = PublicAuthV1Api(public_api_client)

        response: LoginMethodsResponse = pub_auth.auth_v1_get_login_methods(
            email=email,
        )
        assert response.has_password is True

    def test_login_methods_with_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Login methods report a configured password."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Set the password.
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # Fetch the available login methods.
        pub_auth = PublicAuthV1Api(public_api_client)
        response: LoginMethodsResponse = pub_auth.auth_v1_get_login_methods(
            email=email,
        )
        assert response.has_password is True

    def test_login_with_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """A user can log in with a configured password."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Set the password.
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # password login
        pub_auth = PublicAuthV1Api(public_api_client)
        response = pub_auth.auth_v1_login_with_password(
            PasswordLoginRequest(email=email, password="StrongP@ss1!"),
        )
        assert response.access_token is not None
        assert response.refresh_token is not None
        assert response.expires_in > 0

    def test_login_with_wrong_password_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Login with an incorrect password returns 401."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Set the password.
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # Attempt login with the wrong password.
        pub_auth = PublicAuthV1Api(public_api_client)
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            pub_auth.auth_v1_login_with_password(
                PasswordLoginRequest(email=email, password="WrongPassword!"),
            )
        assert exc_info.value.status == 401

    def test_login_with_password_unknown_email_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """Password login with an unknown email returns 401."""
        pub_auth = PublicAuthV1Api(public_api_client)
        email = f"unknown-{unique()}@example.com"

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            pub_auth.auth_v1_login_with_password(
                PasswordLoginRequest(email=email, password="SomePassword1!"),
            )
        assert exc_info.value.status == 401

    def test_login_methods_unknown_email(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """Login methods for an unknown email report no password."""
        pub_auth = PublicAuthV1Api(public_api_client)
        email = f"unknown-{unique()}@example.com"

        response: LoginMethodsResponse = pub_auth.auth_v1_get_login_methods(
            email=email,
        )
        assert response.has_password is False
