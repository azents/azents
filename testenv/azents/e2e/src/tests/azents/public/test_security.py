"""Public Security API E2E test.

password t, step-up auth(elevation), login t fetcht verifyt.
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
    """email OTPt t t elevationt elevated access tokent return."""
    security_api = SecurityV1Api(public_api_client)
    adm_auth = AdminAuthV1Api(admin_api_client)

    # 1. Elevation t t
    send_response = security_api.security_v1_send_elevation_code(
        _headers={"Authorization": f"Bearer {access_token}"},
    )
    csrf_token = send_response.csrf_token

    # 2. Admin APIt t fetch
    verification = adm_auth.auth_v1_get_email_verification_by_email(
        email=email, csrf_token=csrf_token
    )

    # 3. email OTPt elevation
    elevate_response = security_api.security_v1_elevate_with_email(
        ElevateWithEmailRequest(code=verification.code, csrf_token=csrf_token),
        _headers={"Authorization": f"Bearer {access_token}"},
    )
    return elevate_response.access_token


class TestSecurityElevation:
    """Step-up auth(elevation) test."""

    def test_get_auth_methods_without_elevation_returns_403(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Elevated token t auth t fetch t 403t returnt."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        security_api = SecurityV1Api(public_api_client)

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_get_auth_methods(
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 403  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_elevate_with_email_and_get_auth_methods(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """email OTPt elevation t auth t fetcht."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)

        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Elevated tokent auth t fetch
        security_api = SecurityV1Api(public_api_client)
        response = security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )
        assert response.methods is not None
        assert len(response.methods) > 0

        # SMTP disabled fixture t email credential t invalid t.
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
        """t t elevation t 400t returnt."""
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
        assert exc_info.value.status == 400  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_elevation_stripped_on_refresh(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Refresh tokent t t elevationt t."""
        access_token, refresh_token, email = authenticate_user(
            public_api_client, admin_api_client
        )

        # Elevation t
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # Elevated tokent security t t t check
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # Refresh → t tokent elevation t
        pub_auth = PublicAuthV1Api(public_api_client)
        refresh_response = pub_auth.auth_v1_refresh_token(
            RefreshTokenRequest(refresh_token=refresh_token)
        )
        new_access_token = refresh_response.access_token

        # t tokent security t t t 403
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_get_auth_methods(
                _headers={"Authorization": f"Bearer {new_access_token}"},
            )
        assert exc_info.value.status == 403  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t


class TestPasswordManagement:
    """password settings/delete test."""

    def test_set_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """passwordt settingst."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        security_api = SecurityV1Api(public_api_client)
        # 204 No Content return
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # auth t passwordt t
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
        """Elevation t password settings t 403t returnt."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        security_api = SecurityV1Api(public_api_client)

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_set_password(
                SetPasswordRequest(password="StrongP@ss1!"),
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 403  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_remove_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """passwordt deletet."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        security_api = SecurityV1Api(public_api_client)

        # password settings
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # SMTP disabled fixture t t valid credential deletet t
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_remove_password(
                _headers={"Authorization": f"Bearer {elevated_token}"},
            )
        assert exc_info.value.status == 409  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

        # auth t passwordt t valid credential t t
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
        """Signup token redeem t settingst t passwordt deletet."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        security_api = SecurityV1Api(public_api_client)
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_remove_password(
                _headers={"Authorization": f"Bearer {elevated_token}"},
            )
        assert exc_info.value.status == 409  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

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
        """password settings t passwordt elevationt t."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # password settings
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # t sessiont login (password elevation testt t)
        access_token_2, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=email
        )

        # passwordt elevation
        elevate_response = security_api.security_v1_elevate_with_password(
            ElevateWithPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {access_token_2}"},
        )
        assert elevate_response.access_token is not None
        assert elevate_response.expires_in > 0

        # Elevated tokent security t t t
        security_api.security_v1_get_auth_methods(
            _headers={"Authorization": f"Bearer {elevate_response.access_token}"},
        )

    def test_elevate_with_wrong_password_returns_400(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t passwordt elevation t 400t returnt."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # password settings
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # t passwordt elevation t
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            security_api.security_v1_elevate_with_password(
                ElevateWithPasswordRequest(password="WrongPassword!"),
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 400  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t


class TestPasswordLogin:
    """password login test."""

    def test_login_methods_after_signup_token_redeem_has_password(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Signup token redeem t t passwordt t."""
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
        """password settings t login t fetch t has_password=True."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # password settings
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # login t fetch
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
        """passwordt logint."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # password settings
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
        """t passwordt login t 401t returnt."""
        access_token, _, email = authenticate_user(public_api_client, admin_api_client)
        elevated_token = _elevate_user(
            public_api_client, admin_api_client, access_token, email
        )

        # password settings
        security_api = SecurityV1Api(public_api_client)
        security_api.security_v1_set_password(
            SetPasswordRequest(password="StrongP@ss1!"),
            _headers={"Authorization": f"Bearer {elevated_token}"},
        )

        # t passwordt login
        pub_auth = PublicAuthV1Api(public_api_client)
        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            pub_auth.auth_v1_login_with_password(
                PasswordLoginRequest(email=email, password="WrongPassword!"),
            )
        assert exc_info.value.status == 401  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_login_with_password_unknown_email_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """existst t emailt password login t 401t returnt."""
        pub_auth = PublicAuthV1Api(public_api_client)
        email = f"unknown-{unique()}@example.com"

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            pub_auth.auth_v1_login_with_password(
                PasswordLoginRequest(email=email, password="SomePassword1!"),
            )
        assert exc_info.value.status == 401  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_login_methods_unknown_email(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """existst t emailt login t fetch t has_password=False."""
        pub_auth = PublicAuthV1Api(public_api_client)
        email = f"unknown-{unique()}@example.com"

        response: LoginMethodsResponse = pub_auth.auth_v1_get_login_methods(
            email=email,
        )
        assert response.has_password is False
