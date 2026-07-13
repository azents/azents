"""Admin API User CRUD test."""

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.user_v1_api import UserV1Api

from support.utils import authenticate_user, unique


class TestUserCrud:
    """User CRUD t test."""

    def test_list_users(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """autht createt Usert listt t."""
        user_api = UserV1Api(admin_api_client)

        # autht t t create
        authenticate_user(public_api_client, admin_api_client)

        # t list fetch
        response = user_api.user_v1_list_users()
        assert len(response.items) > 0

    def test_get_user(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """autht createt Usert IDt fetcht t t."""
        user_api = UserV1Api(admin_api_client)

        # autht t t create
        authenticate_user(public_api_client, admin_api_client)

        # listt t ID check
        users = user_api.user_v1_list_users()
        assert len(users.items) > 0
        user_id = users.items[0].id

        # IDt t fetch
        user = user_api.user_v1_get_user(user_id)
        assert user.id == user_id

    def test_delete_user(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """Usert deletet 404t returnt."""
        user_api = UserV1Api(admin_api_client)
        email = f"delete-{unique()}@example.com"

        # autht t t create
        authenticate_user(public_api_client, admin_api_client, email=email)

        # listt t t ID t
        users = user_api.user_v1_list_users()
        user_id = None
        for user in users.items:
            if user.primary_email == email:
                user_id = user.id
                break
        assert user_id is not None

        # delete
        user_api.user_v1_delete_user(user_id)

        # delete check
        with pytest.raises(azentsadminclient.ApiException) as exc_info:
            user_api.user_v1_get_user(user_id)
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t


class TestUserValidation:
    """User verify t test."""

    def test_get_user_not_found_returns_404(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """existst t User fetch t 404t returnt."""
        user_api = UserV1Api(admin_api_client)

        with pytest.raises(azentsadminclient.ApiException) as exc_info:
            user_api.user_v1_get_user("00000000-0000-0000-0000-000000000000")
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
