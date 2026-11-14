"""Complete typed configuration for isolated application-composition tests."""

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from azents.core.config import Config, Settings


class _IsolatedSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def isolated_config() -> Config:
    """Build valid configuration without loading ambient settings or secrets."""
    settings = _IsolatedSettings.model_validate(
        {
            "rdb_host": "localhost",
            "rdb_user": "test",
            "rdb_db_name": "test",
            "auth_jwt_secret_key": "synthetic-test-key",
            "credential_encryption_key": (
                "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
            ),
        }
    )
    return Config.from_settings(settings)
