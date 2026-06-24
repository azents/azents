"""Admin API UserEmail CRUD test."""

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.user_email_v1_api import UserEmailV1Api
from azentsadminclient.api.user_v1_api import UserV1Api
from azentsadminclient.models.user_email_create_request import (
    UserEmailCreateRequest,
)

from support.utils import authenticate_user, unique


class TestUserEmailCrud:
    """UserEmail CRUD t test."""

    def _create_user_via_auth(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> str:
        """autht t t createt user_idt return."""
        email = f"ue-{unique()}@example.com"
        authenticate_user(public_api_client, admin_api_client, email=email)

        user_api = UserV1Api(admin_api_client)
        users = user_api.user_v1_list_users()
        # t t t return
        assert len(users.items) > 0
        return users.items[-1].id

    def test_list_emails_by_user(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """User IDt email listt fetcht."""
        user_id = self._create_user_via_auth(public_api_client, admin_api_client)
        email_api = UserEmailV1Api(admin_api_client)

        response = email_api.useremail_v1_list_emails_by_user(user_id)
        # auth t t emailt createt t 1t t
        assert len(response.items) >= 1

    def test_create_email_for_user(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """Usert t emailt createt."""
        user_id = self._create_user_via_auth(public_api_client, admin_api_client)
        email_api = UserEmailV1Api(admin_api_client)

        new_email = f"new-{unique()}@example.com"
        created = email_api.useremail_v1_create_email(
            user_id, UserEmailCreateRequest(email=new_email)
        )
        assert created.email == new_email
        assert created.id is not None

    def test_delete_email(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """emailt deletet."""
        user_id = self._create_user_via_auth(public_api_client, admin_api_client)
        email_api = UserEmailV1Api(admin_api_client)

        # t email create
        new_email = f"del-{unique()}@example.com"
        created = email_api.useremail_v1_create_email(
            user_id, UserEmailCreateRequest(email=new_email)
        )

        # delete
        email_api.useremail_v1_delete_email(created.id)

        # delete check - t email listt removet
        emails = email_api.useremail_v1_list_emails_by_user(user_id)
        email_ids = [e.id for e in emails.items]
        assert created.id not in email_ids

    def test_create_duplicate_email_returns_409(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """t email t create t 409t returnt."""
        user_id = self._create_user_via_auth(public_api_client, admin_api_client)
        email_api = UserEmailV1Api(admin_api_client)

        dup_email = f"dup-{unique()}@example.com"

        # t t create
        email_api.useremail_v1_create_email(
            user_id, UserEmailCreateRequest(email=dup_email)
        )

        # t t t emailt create t
        with pytest.raises(azentsadminclient.ApiException) as exc_info:
            email_api.useremail_v1_create_email(
                user_id, UserEmailCreateRequest(email=dup_email)
            )
        assert exc_info.value.status == 409  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
