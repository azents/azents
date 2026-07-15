"""Application settings.

Loads settings from environment variables and converts them into domain-specific
Config objects.
"""

import datetime
import urllib.parse
from typing import Literal, Self

from azcommon.logging import RuntimeEnvironment
from mypy_boto3_rds import RDSClient
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RegistrationMode = Literal["closed", "signup_token", "open"]


class Settings(BaseSettings):
    """Settings loaded from environment variables.

    Environment variables are mapped with the AZ_ prefix.
    Example: AZ_RDB_HOST -> rdb_host
    """

    model_config = SettingsConfigDict(
        env_prefix="AZ_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Runtime environment
    runtime_env: RuntimeEnvironment = RuntimeEnvironment.LOCAL

    # Sentry
    sentry_dsn: str | None = None

    # Database
    rdb_host: str
    rdb_port: int = 5432
    rdb_user: str
    rdb_password: str | None = None
    rdb_db_name: str
    rdb_use_iam_auth: bool = False
    rdb_region: str = "us-west-2"
    rdb_ssl_mode: str = "prefer"
    rdb_verbose: bool = False

    # Auth - JWT
    auth_jwt_secret_key: str
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_access_token_expire_minutes: int = 30

    # Auth - Refresh Token
    auth_refresh_token_expire_days: int = 180
    auth_refresh_token_max_expire_days: int | None = None
    auth_refresh_token_rotation_period_minutes: int = 10
    auth_refresh_token_grace_period_minutes: int = 5
    auth_registration_mode: RegistrationMode = "signup_token"
    auth_signup_token_default_expire_hours: int = 168
    auth_signup_token_default_max_uses: int = 1

    # Initial system administrator bootstrap
    system_bootstrap_setup_token: str | None = None

    # Email; disabled when email_sender is None
    email_sender: str | None = None
    email_sender_name: str = "Azents"
    email_ses_region: str = "us-west-2"
    email_ses_endpoint: str | None = None
    email_verification_expire_minutes: int = 10

    # Frontend URL for links included in emails
    web_url: str | None = None
    # API server public URL for external callbacks
    api_url: str | None = None

    # LLM credential encryption key; Fernet key, base64-encoded 32 bytes
    credential_encryption_key: str

    # Redis
    redis_url: str = "redis://localhost:6379"

    runtime_default_provider_id: str | None = None

    # Streaming model watchdog
    model_stream_connect_timeout_seconds: float = 15.0
    model_stream_idle_timeout_seconds: float = 300.0
    model_stream_absolute_timeout_seconds: float = 1_800.0
    model_stream_close_grace_seconds: float = 5.0

    # GitHub Platform App (JWT)
    github_platform_app_id: str | None = None
    github_platform_private_key: str | None = None
    # GitHub Platform App; for OAuth installation list lookup
    github_platform_client_id: str | None = None
    github_platform_client_secret: str | None = None
    # OAuth2 for per-user MCP authentication
    oauth_secret_key: str = ""

    # MCP egress proxy; forward proxy for SSRF blocking
    mcp_proxy_url: str | None = None

    # Testenv-only flags; startup fails when enabled in production
    testenv_api_enabled: bool = False
    testenv_runtime_hook_qa_enabled: bool = False

    # Session data S3 storage; unified file storage
    workspace_s3_bucket: str = ""
    workspace_s3_prefix: str = "v1"
    workspace_s3_endpoint_url: str | None = None
    # Explicit credentials. Production keeps None and uses IAM role / ambient session;
    # local dev (RustFS) and testenv inject dummy key/secret only.
    workspace_s3_access_key_id: str | None = None
    workspace_s3_secret_access_key: str | None = None

    # Avatar serving CDN; uses `{cdn_base_url}/{key}` when set, else 1h presigned GET
    avatar_cdn_base_url: str | None = None

    # File lifecycle retention
    artifact_retention_days: int = 7
    exchange_file_retention_days: int = 30


class PostgreSQLConfig(BaseModel):
    """PostgreSQL settings."""

    host: str
    port: int
    user: str
    password: str | None
    db_name: str
    use_iam_auth: bool = False
    region: str = "us-west-2"
    ssl_mode: str = "prefer"
    verbose: bool = False

    def get_sqlalchemy_uri(
        self,
        *,
        with_password: bool = False,
        rds_client: "RDSClient | None" = None,
    ) -> str:
        """Create SQLAlchemy URI.

        .. warning::

            For IAM authentication, the URI returned with ``with_password=True``
            contains a one-time token that expires after 15 minutes. For
            long-lived connections, refresh the token on each connection via the
            ``do_connect`` event.

        :param with_password: When True, return URI including password.
        :param rds_client: RDS client used to create token for IAM authentication.
            Required when ``with_password=True`` and IAM authentication is used.
        :return: SQLAlchemy connection URI
        """
        if with_password:
            password = self._get_password(rds_client=rds_client)
            return (
                f"postgresql+psycopg://{urllib.parse.quote(self.user, safe='')}:"
                f"{urllib.parse.quote(password, safe='')}@"
                f"{self.host}:"
                f"{self.port}/"
                f"{urllib.parse.quote(self.db_name, safe='')}"
            )
        # Create URI without password; token is injected dynamically on connect
        return (
            f"postgresql+psycopg://{urllib.parse.quote(self.user, safe='')}@"
            f"{self.host}:"
            f"{self.port}/"
            f"{urllib.parse.quote(self.db_name, safe='')}"
        )

    def _get_password(self, *, rds_client: "RDSClient | None" = None) -> str:
        """Return password for authentication.

        :param rds_client: RDS client used to create token for IAM authentication.
        :return: Password or empty string
        """
        if self.use_iam_auth:
            if rds_client is None:
                raise ValueError("rds_client is required for IAM authentication")
            token: str = rds_client.generate_db_auth_token(
                DBHostname=self.host,
                Port=self.port,
                DBUsername=self.user,
                Region=self.region,
            )
            return token
        return self.password or ""


class JWTConfig(BaseModel):
    """JWT settings."""

    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    @property
    def access_token_expire_seconds(self) -> int:
        """Access token expiration time in seconds."""
        return self.access_token_expire_minutes * 60


class RefreshTokenConfig(BaseModel):
    """Refresh Token settings."""

    expire_days: int = 180
    max_expire_days: int | None = None
    rotation_period_minutes: int = 10
    grace_period_minutes: int = 5

    @property
    def expire_timedelta(self) -> datetime.timedelta:
        """Refresh token expiration timedelta."""
        return datetime.timedelta(days=self.expire_days)

    @property
    def max_expire_timedelta(self) -> datetime.timedelta | None:
        """Maximum refresh token expiration timedelta."""
        if self.max_expire_days is None:
            return None
        return datetime.timedelta(days=self.max_expire_days)

    @property
    def rotation_period(self) -> datetime.timedelta:
        """Refresh token rotation interval."""
        return datetime.timedelta(minutes=self.rotation_period_minutes)

    @property
    def grace_period(self) -> datetime.timedelta:
        """Previous token validity period."""
        return datetime.timedelta(minutes=self.grace_period_minutes)


class EmailConfig(BaseModel):
    """Email sending settings."""

    sender: str
    sender_name: str = "Azents"
    ses_region: str = "us-west-2"
    ses_endpoint: str | None = None
    verification_expire_minutes: int = 10
    web_url: str | None = None

    @property
    def verification_expire_timedelta(self) -> datetime.timedelta:
        """Authentication code expiration timedelta."""
        return datetime.timedelta(minutes=self.verification_expire_minutes)


class SignupTokenConfig(BaseModel):
    """Signup token settings."""

    default_expire_hours: int = 168
    default_max_uses: int = 1

    @property
    def default_expire_timedelta(self) -> datetime.timedelta:
        """Default signup token expiration timedelta."""
        return datetime.timedelta(hours=self.default_expire_hours)


class AuthConfig(BaseModel):
    """Authentication settings."""

    jwt: JWTConfig
    refresh_token: RefreshTokenConfig
    registration_mode: RegistrationMode = "signup_token"
    signup_token: SignupTokenConfig


class SystemBootstrapConfig(BaseModel):
    """Initial system administrator bootstrap settings."""

    setup_token: str | None


class GitHubConfig(BaseModel):
    """GitHub Platform settings."""

    platform_app_id: str | None = None
    platform_private_key: str | None = None
    platform_client_id: str | None = None
    platform_client_secret: str | None = None


class CredentialEncryptionConfig(BaseModel):
    """Credential encryption settings."""

    key: str


class RedisConfig(BaseModel):
    """Redis settings."""

    url: str


class RuntimeConfig(BaseModel):
    """Agent Runtime settings."""

    default_provider_id: str | None = None


class ModelStreamTimeoutConfig(BaseModel):
    """Validated process-wide streaming model watchdog settings."""

    connect_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    parsed_event_idle_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    absolute_attempt_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    close_grace_seconds: float = Field(gt=0, allow_inf_nan=False)


class FileLifecycleConfig(BaseModel):
    """File lifecycle retention settings."""

    artifact_retention_days: int = 7
    exchange_file_retention_days: int = 30

    @property
    def artifact_ttl(self) -> datetime.timedelta:
        """Artifact retention duration."""
        return datetime.timedelta(days=self.artifact_retention_days)

    @property
    def exchange_file_ttl(self) -> datetime.timedelta:
        """ExchangeFile retention duration."""
        return datetime.timedelta(days=self.exchange_file_retention_days)


class WorkspaceS3Credentials(BaseModel):
    """Explicit credentials for Workspace S3 access.

    Production environments using AWS IAM roles leave this as ``None`` and use
    ambient session. Only local dev (RustFS) / testenv inject dummy
    key/secret explicitly.
    """

    access_key_id: str
    secret_access_key: str


class WorkspaceS3Config(BaseModel):
    """Workspace S3 settings for unified file storage.

    Single shared bucket for user-uploaded files such as agent avatars and
    session files. ``credentials`` is optional; when unset, ambient AWS session
    such as IAM role is used.
    """

    bucket: str
    prefix: str = "v1"
    endpoint_url: str | None = None
    credentials: WorkspaceS3Credentials | None = None


class Config(BaseModel):
    """Application settings, immutable and type-safe."""

    runtime_env: RuntimeEnvironment
    sentry_dsn: str | None
    rdb: PostgreSQLConfig
    auth: AuthConfig
    system_bootstrap: SystemBootstrapConfig
    email: EmailConfig | None
    credential_encryption: CredentialEncryptionConfig
    redis: RedisConfig
    runtime: RuntimeConfig
    model_stream_timeout: ModelStreamTimeoutConfig
    github: GitHubConfig | None = None
    web_url: str = ""
    api_url: str = ""
    oauth_secret_key: str = ""
    mcp_proxy_url: str | None = None
    workspace_s3: WorkspaceS3Config
    file_lifecycle: FileLifecycleConfig = FileLifecycleConfig()
    avatar_cdn_base_url: str | None = None
    # Testenv-only flags
    testenv_api_enabled: bool = False
    testenv_runtime_hook_qa_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Create Config from Settings."""
        return cls(
            runtime_env=settings.runtime_env,
            sentry_dsn=settings.sentry_dsn,
            rdb=PostgreSQLConfig(
                host=settings.rdb_host,
                port=settings.rdb_port,
                user=settings.rdb_user,
                password=settings.rdb_password,
                db_name=settings.rdb_db_name,
                use_iam_auth=settings.rdb_use_iam_auth,
                region=settings.rdb_region,
                ssl_mode=settings.rdb_ssl_mode,
                verbose=settings.rdb_verbose,
            ),
            auth=AuthConfig(
                jwt=JWTConfig(
                    secret_key=settings.auth_jwt_secret_key,
                    algorithm=settings.auth_jwt_algorithm,
                    access_token_expire_minutes=settings.auth_jwt_access_token_expire_minutes,
                ),
                refresh_token=RefreshTokenConfig(
                    expire_days=settings.auth_refresh_token_expire_days,
                    max_expire_days=settings.auth_refresh_token_max_expire_days,
                    rotation_period_minutes=settings.auth_refresh_token_rotation_period_minutes,
                    grace_period_minutes=settings.auth_refresh_token_grace_period_minutes,
                ),
                registration_mode=settings.auth_registration_mode,
                signup_token=SignupTokenConfig(
                    default_expire_hours=settings.auth_signup_token_default_expire_hours,
                    default_max_uses=settings.auth_signup_token_default_max_uses,
                ),
            ),
            system_bootstrap=SystemBootstrapConfig(
                setup_token=settings.system_bootstrap_setup_token,
            ),
            email=EmailConfig(
                sender=settings.email_sender,
                sender_name=settings.email_sender_name,
                ses_region=settings.email_ses_region,
                ses_endpoint=settings.email_ses_endpoint,
                verification_expire_minutes=settings.email_verification_expire_minutes,
                web_url=settings.web_url,
            )
            if settings.email_sender is not None
            else None,
            credential_encryption=CredentialEncryptionConfig(
                key=settings.credential_encryption_key,
            ),
            redis=RedisConfig(
                url=settings.redis_url,
            ),
            runtime=RuntimeConfig(
                default_provider_id=settings.runtime_default_provider_id,
            ),
            model_stream_timeout=ModelStreamTimeoutConfig(
                connect_timeout_seconds=(settings.model_stream_connect_timeout_seconds),
                parsed_event_idle_timeout_seconds=(
                    settings.model_stream_idle_timeout_seconds
                ),
                absolute_attempt_timeout_seconds=(
                    settings.model_stream_absolute_timeout_seconds
                ),
                close_grace_seconds=settings.model_stream_close_grace_seconds,
            ),
            github=GitHubConfig(
                platform_app_id=settings.github_platform_app_id,
                platform_private_key=settings.github_platform_private_key,
                platform_client_id=settings.github_platform_client_id,
                platform_client_secret=settings.github_platform_client_secret,
            )
            if (
                settings.github_platform_app_id is not None
                or settings.github_platform_client_id is not None
            )
            else None,
            web_url=settings.web_url or "",
            api_url=settings.api_url or "",
            oauth_secret_key=settings.oauth_secret_key,
            mcp_proxy_url=settings.mcp_proxy_url,
            workspace_s3=WorkspaceS3Config(
                bucket=settings.workspace_s3_bucket,
                prefix=settings.workspace_s3_prefix,
                endpoint_url=settings.workspace_s3_endpoint_url,
                credentials=(
                    WorkspaceS3Credentials(
                        access_key_id=settings.workspace_s3_access_key_id,
                        secret_access_key=settings.workspace_s3_secret_access_key,
                    )
                    if settings.workspace_s3_access_key_id is not None
                    and settings.workspace_s3_secret_access_key is not None
                    else None
                ),
            ),
            file_lifecycle=FileLifecycleConfig(
                artifact_retention_days=settings.artifact_retention_days,
                exchange_file_retention_days=settings.exchange_file_retention_days,
            ),
            avatar_cdn_base_url=settings.avatar_cdn_base_url,
            testenv_api_enabled=settings.testenv_api_enabled,
            testenv_runtime_hook_qa_enabled=settings.testenv_runtime_hook_qa_enabled,
        )

    @classmethod
    def from_env(cls) -> Self:
        """Create Config from environment variables.

        The pydantic-settings Settings class automatically loads values from
        environment variables. Required Settings fields such as rdb_host have no
        default, but pydantic-settings injects values from environment variables
        such as AZ_RDB_HOST at runtime, so Settings() works without arguments.

        pyright does not understand this runtime behavior and reports missing
        required arguments. Since pydantic pyright plugin does not support
        BaseSettings, suppress the error only in this wrapper function.
        """
        return cls.from_settings(Settings())  # type: ignore[call-arg]
