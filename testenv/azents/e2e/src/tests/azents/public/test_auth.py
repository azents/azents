"""Public Auth API E2E test."""

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.auth_v1_api import AuthV1Api as AdminAuthV1Api
from azentspublicclient.api.auth_v1_api import AuthV1Api as PublicAuthV1Api
from azentspublicclient.models.refresh_token_request import RefreshTokenRequest
from azentspublicclient.models.send_code_request import SendCodeRequest
from azentspublicclient.models.verify_code_request import VerifyCodeRequest

from support.utils import authenticate_user, unique


class TestUnifiedAuth:
    """integration email auth t test."""

    def test_send_code_success(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """auth t t t csrf_tokent returnt."""
        pub_auth = PublicAuthV1Api(public_api_client)
        email = f"test-{unique()}@example.com"

        response = pub_auth.auth_v1_send_code(SendCodeRequest(email=email))
        assert response.csrf_token is not None
        assert len(response.csrf_token) > 0

    def test_verify_code_new_user_requires_signup_token(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t email OTP verifyt signup token t t returnt."""
        pub_auth = PublicAuthV1Api(public_api_client)
        adm_auth = AdminAuthV1Api(admin_api_client)
        email = f"test-{unique()}@example.com"

        send_response = pub_auth.auth_v1_send_code(SendCodeRequest(email=email))
        csrf_token = send_response.csrf_token
        verification = adm_auth.auth_v1_get_email_verification_by_email(
            email=email, csrf_token=csrf_token
        )
        assert verification.code is not None

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            pub_auth.auth_v1_verify_code(
                VerifyCodeRequest(
                    email=email, code=verification.code, csrf_token=csrf_token
                )
            )
        assert exc_info.value.status == 403  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_verify_code_existing_user(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t emailt t t auth t t t tuset."""
        email = f"test-{unique()}@example.com"

        # t t auth
        access_token_1, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=email
        )
        assert access_token_1 is not None

        # t t auth (t email)t email OTP login t t
        pub_auth = PublicAuthV1Api(public_api_client)
        adm_auth = AdminAuthV1Api(admin_api_client)
        send_response = pub_auth.auth_v1_send_code(SendCodeRequest(email=email))
        verification = adm_auth.auth_v1_get_email_verification_by_email(
            email=email, csrf_token=send_response.csrf_token
        )
        verify_response = pub_auth.auth_v1_verify_code(
            VerifyCodeRequest(
                email=email,
                code=verification.code,
                csrf_token=send_response.csrf_token,
            )
        )
        assert verify_response.access_token is not None

    def test_verify_code_wrong_code_returns_400(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """t t verify t 400t returnt."""
        pub_auth = PublicAuthV1Api(public_api_client)
        email = f"test-{unique()}@example.com"

        send_response = pub_auth.auth_v1_send_code(SendCodeRequest(email=email))

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            pub_auth.auth_v1_verify_code(
                VerifyCodeRequest(
                    email=email,
                    code="WRONG1",
                    csrf_token=send_response.csrf_token,
                )
            )
        assert exc_info.value.status == 400  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_verify_code_wrong_csrf_returns_400(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """t CSRF tokent verify t 400t returnt."""
        pub_auth = PublicAuthV1Api(public_api_client)
        email = f"test-{unique()}@example.com"

        pub_auth.auth_v1_send_code(SendCodeRequest(email=email))

        with pytest.raises(azentspublicclient.ApiException) as exc_info:
            pub_auth.auth_v1_verify_code(
                VerifyCodeRequest(
                    email=email,
                    code="123456",
                    csrf_token="invalid-csrf-token",
                )
            )
        assert exc_info.value.status == 400  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_refresh_token_success(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """refresh tokent t tokent t."""
        _, refresh_token, _ = authenticate_user(public_api_client, admin_api_client)

        pub_auth = PublicAuthV1Api(public_api_client)
        response = pub_auth.auth_v1_refresh_token(
            RefreshTokenRequest(refresh_token=refresh_token)
        )
        assert response.access_token is not None
        assert response.refresh_token is not None
        assert response.expires_in > 0

    def test_logout_success(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """logoutt t t."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)

        pub_auth = PublicAuthV1Api(public_api_client)
        pub_auth.auth_v1_logout(
            _headers={"Authorization": f"Bearer {access_token}"},
        )
