"""EnvVarToolkit — general-purpose environment variable injection Toolkit.

When workspace manager registers arbitrary environment variables such as API
keys, they are injected into child process env during agent session ``shell()``
execution. This is not specialized for a specific service and applies to every
service that supports env-based authentication, such as Notion / OpenAI / Sentry.

Design context: docs/azents/design/runtime-credential-injection.md
"""

import logging
import re

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)

logger = logging.getLogger(__name__)

# POSIX environment variable name validation regex. Prevents shell injection.
_ENV_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Validation constants
_MAX_ENTRY_NAME_LEN = 64
_MAX_ENTRY_VALUE_LEN = 4096
_MAX_TOTAL_PAYLOAD_LEN = 100 * 1024
_MAX_ENTRY_COUNT = 50


class EnvEntryMeta(BaseModel):
    """Environment variable entry metadata.

    Values are separately encrypted in ``EnvVarToolkitSecrets``; this model keeps
    only plaintext metadata (name / masking flag).
    """

    name: str = Field(
        description="POSIX environment variable name (^[A-Z_][A-Z0-9_]*$).",
    )
    masked: bool = Field(
        default=True,
        description="Whether to mask value in audit log. Default is true.",
    )


class EnvVarToolkitConfig(BaseModel):
    """EnvVarToolkit configuration (plaintext).

    Stored as-is in DB ``toolkit_configs.config`` JSONB field.
    """

    entries: list[EnvEntryMeta] = Field(
        default_factory=list,
        description="Registered environment variable names.",
    )


class EnvVarToolkitSecrets(BaseModel):
    """EnvVarToolkit encrypted secret body.

    Serialized as JSON and Fernet-encrypted in DB
    ``toolkit_configs.encrypted_credentials`` field.
    """

    values: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variable name to value mapping.",
    )


class EnvVarToolkit(Toolkit[EnvVarToolkitConfig]):
    """EnvVarToolkit execution instance.

    Does not expose tools and only supplies env during shell execution through
    ``expose_env()``. Only names declared in ``config.entries`` act as allowlist,
    so removed config values are not exposed, even if credentials remain.
    """

    def __init__(
        self,
        *,
        config: EnvVarToolkitConfig,
        values: dict[str, str],
        toolkit_name: str,
    ) -> None:
        """Initialize.

        :param config: Toolkit settings (entry metadata)
        :param values: Decrypted env values. Keys inconsistent with config are
            filtered on expose.
        :param toolkit_name: Human-readable toolkit name for prompt/log.
        """
        self._config = config
        self._values = values
        self.display_name = toolkit_name

    async def update_context(self, context: TurnContext) -> ToolkitState:  # noqa: ARG002
        """Return enabled tool state; env prompt is collected separately."""
        return ToolkitState(tools=[], status=ToolkitStatus.ENABLED)

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static environment variable prompt for the current run."""
        del context
        entry_names = [entry.name for entry in self._config.entries]
        if not entry_names:
            return ""
        refs = ", ".join(f"${name}" for name in entry_names)
        return (
            f"Environment variables available in shell commands "
            f"via '{self.display_name}': {refs}"
        )

    async def expose_env(self) -> dict[str, str]:
        """Filter and return only env names declared in config.

        Even when credential store has value, do not expose it if it is not declared in
        config; config acts as permission boundary.
        """
        allowlist = {entry.name for entry in self._config.entries}
        return {
            name: value for name, value in self._values.items() if name in allowlist
        }


class EnvVarToolkitProvider(ToolkitProvider[EnvVarToolkitConfig]):
    """EnvVarToolkit provider.

    At ``resolve()`` time, receives encrypted credentials_json from DB, parses it,
    and creates ``EnvVarToolkit`` instance. There is no credential exchange/refresh;
    static long-lived token is injected as-is.
    """

    slug = "envvar"
    name = "Environment Variables"
    description = (
        "Arbitrary environment variables injected into runtime shell commands. "
        "Useful for long-lived API tokens (Notion, OpenAI, Sentry, etc)."
    )
    system_prompt = (
        "Environment variables configured through this toolkit are exposed to "
        "shell commands. Reference them in shell commands (e.g., $NOTION_TOKEN). "
        "Do not echo or log their values."
    )
    config_model = EnvVarToolkitConfig

    async def resolve(
        self,
        config: EnvVarToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[EnvVarToolkitConfig]:
        """config + credentials -> EnvVarToolkit instance.

        On successful parsing, record audit log with entry names only. Never log values.
        """
        values: dict[str, str] = {}
        if context.credentials_json:
            try:
                secrets = EnvVarToolkitSecrets.model_validate_json(
                    context.credentials_json
                )
                values = secrets.values
            except ValueError:
                logger.exception(
                    "Failed to parse EnvVar toolkit credentials",
                    extra={"toolkit_id": context.toolkit_id},
                )
                # On parse failure, fall back to empty values.
                values = {}

        # audit: record which toolkit will expose which keys at resolve time
        # Never log values; only key set and toolkit id.
        logger.info(
            "EnvVar toolkit resolved",
            extra={
                "event": "envvar_toolkit.resolved",
                "toolkit_id": context.toolkit_id,
                "workspace_id": context.workspace_id,
                "user_id": context.user_id,
                "entry_names": sorted(e.name for e in config.entries),
                "values_count": len(values),
            },
        )

        return EnvVarToolkit(
            config=config,
            values=values,
            toolkit_name=context.toolkit_name,
        )

    async def validate_credentials(
        self,
        session: AsyncSession,  # noqa: ARG002
        user_id: str,  # noqa: ARG002
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Validate Credentials.

        Checks the following:
        - ``values`` dict schema
        - Each key follows POSIX variable name rule (``^[A-Z_][A-Z0-9_]*$``)
        - Each key length (maximum 64 chars)
        - Each value length (maximum 4KB)
        - Total entry count (maximum 50)
        - Total payload size (maximum 100KB)

        :param session: DB session (unused, protocol compatibility)
        :param user_id: User ID (unused, protocol compatibility)
        :param credentials: Plaintext credentials dict before encryption, or None
        :return: Error message on failure, or None on success
        """
        if credentials is None:
            return None

        try:
            parsed = EnvVarToolkitSecrets.model_validate(credentials)
        except ValueError as exc:
            return f"Invalid credentials schema: {exc}"

        values = parsed.values
        if len(values) > _MAX_ENTRY_COUNT:
            return f"Too many entries ({len(values)}); maximum is {_MAX_ENTRY_COUNT}"

        total_size = 0
        for name, value in values.items():
            if not _ENV_NAME_RE.match(name):
                return f"Invalid entry name '{name}'; must match ^[A-Z_][A-Z0-9_]*$"
            if len(name) > _MAX_ENTRY_NAME_LEN:
                return (
                    f"Entry name too long ({len(name)} chars); "
                    f"maximum is {_MAX_ENTRY_NAME_LEN}"
                )
            if len(value) > _MAX_ENTRY_VALUE_LEN:
                return (
                    f"Entry '{name}' value too long ({len(value)} chars); "
                    f"maximum is {_MAX_ENTRY_VALUE_LEN}"
                )
            total_size += len(name) + len(value)

        if total_size > _MAX_TOTAL_PAYLOAD_LEN:
            return (
                f"Total payload too large ({total_size} bytes); "
                f"maximum is {_MAX_TOTAL_PAYLOAD_LEN}"
            )

        return None
