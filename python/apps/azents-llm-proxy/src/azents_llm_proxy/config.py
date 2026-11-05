"""Deployment-only options; Agent settings remain the model/account authority."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AZ_LLM_PROXY_", extra="forbid", hide_input_in_errors=True
    )

    authority_url: str
    resolver_key: SecretStr | None = Field(default=None, min_length=32, repr=False)
    resolver_token_file: Path | None = None
    authority_ca_file: Path | None = None
    authority_timeout_seconds: float = Field(default=15, gt=0, allow_inf_nan=False)
    port: int = Field(default=4000, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_resolver_identity(self) -> "Settings":
        if (self.resolver_key is None) == (self.resolver_token_file is None):
            raise ValueError("Configure exactly one resolver credential source.")
        return self

    @field_validator("authority_url")
    @classmethod
    def validate_authority_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/internal/llm"
        ):
            raise ValueError(
                "Authority requires a credential-free HTTPS /internal/llm URL."
            )
        return value.rstrip("/") + "/"
