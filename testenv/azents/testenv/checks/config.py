"""Configuration preflight checks.

Checks that the `.env` file exists, required environment variables are present,
and secret values use the expected format. After `env-file-exists` passes, the
runner loads `.env` into `context.env` and fills missing `os.environ` entries.
"""

import base64
import textwrap

from .base import Check, CheckResult, RunContext, Status

_REQUIRED_VARS = (
    "AZ_RDB_HOST",
    "AZ_RDB_PORT",
    "AZ_RDB_USER",
    "AZ_RDB_PASSWORD",
    "AZ_RDB_DB_NAME",
    "AZ_AUTH_JWT_SECRET_KEY",
    "AZ_REDIS_URL",
    "AZ_WORKSPACE_S3_BUCKET",
    "AZ_WORKSPACE_S3_ENDPOINT_URL",
)


class EnvFileExists(Check):
    """Check that `testenv/azents/.env` exists.

    The testenv uses its own `.env`; it does not read `python/apps/azents/.env`.
    """

    def __init__(self) -> None:
        super().__init__(
            id="env-file-exists",
            name=".env file exists",
            category="config",
        )

    def run(self, context: RunContext) -> CheckResult:
        if context.env_file.is_file():
            return CheckResult(status=Status.PASS, message=str(context.env_file))
        return CheckResult(
            status=Status.FAIL,
            message=f"{context.env_file} not found",
            fix_hint="cp testenv/azents/.env.example testenv/azents/.env && edit",
        )


class RequiredEnvVars(Check):
    """Check required AZ_* variables and credential key format."""

    def __init__(self) -> None:
        super().__init__(
            id="required-env-vars",
            name="Required AZ_* variables",
            category="config",
        )

    def run(self, context: RunContext) -> CheckResult:
        missing = [var for var in _REQUIRED_VARS if not context.env.get(var)]
        if missing:
            return CheckResult(
                status=Status.FAIL,
                message=f"missing: {', '.join(missing)}",
                fix_hint="See testenv/azents/.env.example",
            )

        key = context.env.get("AZ_CREDENTIAL_ENCRYPTION_KEY", "")
        if not key:
            return CheckResult(
                status=Status.FAIL,
                message="AZ_CREDENTIAL_ENCRYPTION_KEY is empty",
                fix_hint=textwrap.dedent(
                    """\
                    Generate with:
                      python -c 'import base64, os; \
                    print(base64.b64encode(os.urandom(32)).decode())'
                    """
                ).strip(),
            )
        try:
            decoded = base64.b64decode(key, validate=True)
        except Exception:
            return CheckResult(
                status=Status.FAIL,
                message="AZ_CREDENTIAL_ENCRYPTION_KEY is not valid base64",
                fix_hint="Value must be base64-encoded 32 random bytes",
            )
        if len(decoded) != 32:
            return CheckResult(
                status=Status.FAIL,
                message=f"AZ_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes (got {len(decoded)})",  # noqa: E501
                fix_hint="Value must be base64-encoded 32 random bytes",
            )
        return CheckResult(status=Status.PASS)


class LLMApiKeyAvailable(Check):
    """Check whether credentials for a chat-capable LLM vendor are available.

    Live chat tests need a real LLM call. Without credentials, assertions such
    as `run_complete` and `has_text_content` can fail. This preflight emits WARN
    instead of FAIL because deterministic tests can still run without live LLMs.

    Supported vendors:
    - OpenAI: `OPENAI_API_KEY`
    - Anthropic: `ANTHROPIC_API_KEY`
    - AWS Bedrock: Bedrock secrets stored in AWS SSM Parameter Store, fetched
      using AWS credentials from `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`
      or `AWS_PROFILE`. Actual SSM fetches are performed by setup commands.
    """

    _SINGLE_KEY_VENDORS: tuple[tuple[str, str], ...] = (
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    )

    def __init__(self) -> None:
        super().__init__(
            id="llm-api-key-set",
            name="LLM API key available",
            category="config",
        )

    def run(self, context: RunContext) -> CheckResult:
        available: list[str] = []
        for vendor, key in self._SINGLE_KEY_VENDORS:
            if context.env.get(key):
                available.append(f"{vendor} ({key})")
        # Bedrock secrets live in SSM (`/testenv/azents/bedrock/*`). This check only
        # verifies local AWS credentials; setup commands perform the actual SSM fetch.
        if context.env.get("AWS_ACCESS_KEY_ID") and context.env.get("AWS_SECRET_ACCESS_KEY"):
            available.append("bedrock via SSM (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)")
        elif context.env.get("AWS_PROFILE"):
            available.append("bedrock via SSM (AWS_PROFILE — SDK resolves credentials)")
        if available:
            return CheckResult(
                status=Status.PASS,
                message=f"available: {', '.join(available)}",
            )
        return CheckResult(
            status=Status.WARN,
            message=(
                "no LLM credentials (openai/anthropic/bedrock) — "
                "live chat will not get real responses"
            ),
            fix_hint=(
                "set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, "
                "AWS_ACCESS_KEY_ID+AWS_SECRET_ACCESS_KEY, or AWS_PROFILE. "
                "Bedrock credentials are pulled from SSM (/testenv/azents/bedrock/*) "
                "using the machine's AWS credentials."
            ),
        )
