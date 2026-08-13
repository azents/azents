"""Public API account locale tests."""

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.user_v1_api import UserV1Api
from azentspublicclient.models.update_my_user_request import UpdateMyUserRequest

from support.utils import authenticate_user


class TestUserLocale:
    """Account locale API behavior."""

    def test_get_and_update_locale(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Account locale defaults to English and persists updates."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}
        user_api = UserV1Api(public_api_client)

        initial = user_api.user_v1_me(_headers=headers)
        assert initial.locale == "en-US"

        updated = user_api.user_v1_update_me(
            UpdateMyUserRequest(locale="ja-JP"),
            _headers=headers,
        )
        assert updated.locale == "ja-JP"

        current = user_api.user_v1_me(_headers=headers)
        assert current.locale == "ja-JP"
