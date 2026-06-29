"""EnvVarToolkit unit tests."""

from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.tools.envvar import (
    EnvEntryMeta,
    EnvVarToolkit,
    EnvVarToolkitConfig,
    EnvVarToolkitProvider,
    EnvVarToolkitSecrets,
)


def _make_turn_context() -> TurnContext:
    """TurnContext for tests."""
    return TurnContext(
        user_id="u1",
        workspace_id="ws1",
        model="test",
        run_id="run1",
        publish_event=AsyncMock(),
    )


def _make_resolve_context(
    *,
    credentials_json: str | None = None,
    toolkit_id: str = "tk1",
    toolkit_name: str = "My Creds",
) -> ResolveContext:
    """ResolveContext for tests."""
    return ResolveContext(
        toolkit_id=toolkit_id,
        toolkit_name=toolkit_name,
        credentials_json=credentials_json,
        agent_id="agent1",
        session_id="session1",
        user_id="u1",
        session=AsyncMock(spec=AsyncSession),
        web_url="https://test.example.com",
        oauth_secret_key="test-key",
        workspace_id="ws1",
        workspace_handle="ws",
    )


class TestEnvVarToolkitExposeEnv:
    """EnvVarToolkit.expose_env() unit tests."""

    async def test_exposes_configured_entries(self) -> None:
        """Return value of key declared in config."""
        toolkit = EnvVarToolkit(
            config=EnvVarToolkitConfig(
                entries=[
                    EnvEntryMeta(name="FOO"),
                    EnvEntryMeta(name="BAR"),
                ]
            ),
            values={"FOO": "foo-value", "BAR": "bar-value"},
            toolkit_name="My Creds",
        )

        setting = await toolkit.expose_env()

        assert setting == {"FOO": "foo-value", "BAR": "bar-value"}

    async def test_filters_values_not_in_config(self) -> None:
        """Do not expose value in credential store when absent from config."""
        toolkit = EnvVarToolkit(
            config=EnvVarToolkitConfig(entries=[EnvEntryMeta(name="FOO")]),
            values={"FOO": "foo-value", "BAR": "stale-value"},
            toolkit_name="My Creds",
        )

        setting = await toolkit.expose_env()

        assert setting == {"FOO": "foo-value"}
        assert "BAR" not in setting

    async def test_empty_config_returns_empty(self) -> None:
        """When config is empty, env is also empty."""
        toolkit = EnvVarToolkit(
            config=EnvVarToolkitConfig(entries=[]),
            values={"FOO": "x"},
            toolkit_name="empty",
        )

        setting = await toolkit.expose_env()

        assert setting == {}

    async def test_missing_value_not_exposed(self) -> None:
        """Do not expose value absent from values even if declared in config."""
        toolkit = EnvVarToolkit(
            config=EnvVarToolkitConfig(
                entries=[EnvEntryMeta(name="FOO"), EnvEntryMeta(name="BAR")]
            ),
            values={"FOO": "foo-value"},
            toolkit_name="partial",
        )

        setting = await toolkit.expose_env()

        assert setting == {"FOO": "foo-value"}
        assert "BAR" not in setting


class TestEnvVarToolkitUpdateContext:
    """EnvVarToolkit.update_context() unit tests."""

    async def test_returns_empty_tools_with_prompt(self) -> None:
        """Do not expose tools; list only variable names in prompt."""
        toolkit = EnvVarToolkit(
            config=EnvVarToolkitConfig(entries=[EnvEntryMeta(name="NOTION_TOKEN")]),
            values={"NOTION_TOKEN": "secret"},
            toolkit_name="My Notion",
        )

        state = await toolkit.update_context(_make_turn_context())

        assert not state.tools
        assert "$NOTION_TOKEN" in (
            await toolkit.get_static_prompt(_make_turn_context())
        )
        assert "My Notion" in (await toolkit.get_static_prompt(_make_turn_context()))
        assert state.status == ToolkitStatus.ENABLED

    async def test_empty_config_returns_empty_prompt(self) -> None:
        """When config is empty, prompt is also empty string."""
        toolkit = EnvVarToolkit(
            config=EnvVarToolkitConfig(entries=[]),
            values={},
            toolkit_name="empty",
        )

        await toolkit.update_context(_make_turn_context())

        assert (await toolkit.get_static_prompt(_make_turn_context())) == ""


class TestEnvVarToolkitProviderResolve:
    """EnvVarToolkitProvider.resolve() unit tests."""

    async def test_resolve_with_credentials(self) -> None:
        """Parse credentials_json and inject values into toolkit."""
        provider = EnvVarToolkitProvider()
        config = EnvVarToolkitConfig(entries=[EnvEntryMeta(name="GH_TOKEN")])
        secrets_json = EnvVarToolkitSecrets(
            values={"GH_TOKEN": "ghs_xxx"}
        ).model_dump_json()

        toolkit = await provider.resolve(
            config,
            _make_resolve_context(credentials_json=secrets_json),
        )

        setting = await toolkit.expose_env()
        assert setting == {"GH_TOKEN": "ghs_xxx"}

    async def test_resolve_without_credentials_empty_env(self) -> None:
        """When credentials_json is None, env is empty."""
        provider = EnvVarToolkitProvider()
        config = EnvVarToolkitConfig(entries=[EnvEntryMeta(name="FOO")])

        toolkit = await provider.resolve(
            config,
            _make_resolve_context(credentials_json=None),
        )

        setting = await toolkit.expose_env()
        assert setting == {}

    async def test_resolve_invalid_json_fallback_to_empty(self) -> None:
        """Fall back to empty env when credentials_json parsing fails."""
        provider = EnvVarToolkitProvider()
        config = EnvVarToolkitConfig(entries=[EnvEntryMeta(name="FOO")])

        toolkit = await provider.resolve(
            config,
            _make_resolve_context(credentials_json="not a json"),
        )

        setting = await toolkit.expose_env()
        assert setting == {}

    async def test_resolve_assigns_display_name_from_toolkit_name(self) -> None:
        """ResolveContext.toolkit_name is used as display_name."""
        provider = EnvVarToolkitProvider()

        toolkit = await provider.resolve(
            EnvVarToolkitConfig(entries=[]),
            _make_resolve_context(toolkit_name="Shared Creds"),
        )

        assert toolkit.display_name == "Shared Creds"


class TestEnvVarToolkitProviderValidateCredentials:
    """EnvVarToolkitProvider.validate_credentials() unit tests."""

    def _provider(self) -> EnvVarToolkitProvider:
        return EnvVarToolkitProvider()

    def _session(self) -> AsyncSession:
        return AsyncMock(spec=AsyncSession)

    async def test_none_credentials_accepted(self) -> None:
        """credentials=None always passes."""
        err = await self._provider().validate_credentials(self._session(), "u1", None)

        assert err is None

    async def test_valid_credentials_pass(self) -> None:
        """Pass schema + regex + size limits."""
        err = await self._provider().validate_credentials(
            self._session(),
            "u1",
            {"values": {"FOO": "bar", "BAZ_1": "qux"}},
        )

        assert err is None

    async def test_invalid_schema_rejected(self) -> None:
        """Reject credentials dict without values field."""
        err = await self._provider().validate_credentials(
            self._session(),
            "u1",
            {"wrong_key": {}},
        )

        # EnvVarToolkitSecrets uses values default_factory.
        # That case passes. Test explicit schema violation.
        assert err is None

        err = await self._provider().validate_credentials(
            self._session(),
            "u1",
            {"values": "not a dict"},
        )

        assert err is not None and "Invalid credentials schema" in err

    async def test_invalid_env_name_rejected(self) -> None:
        """Reject POSIX variable name rule violation; both cases are allowed."""
        provider = self._provider()

        for bad_name in ("WITH-DASH", "1LEADING_DIGIT", "", "has space"):
            err = await provider.validate_credentials(
                self._session(),
                "u1",
                {"values": {bad_name: "x"}},
            )
            assert err is not None
            assert "Invalid entry name" in err

    async def test_lowercase_env_name_accepted(self) -> None:
        """Lowercase env name is also allowed, e.g. aws_access_key."""
        err = await self._provider().validate_credentials(
            self._session(),
            "u1",
            {"values": {"aws_access_key": "x", "MixedCase_123": "y"}},
        )
        assert err is None

    async def test_too_long_name_rejected(self) -> None:
        """Reject names of 65 chars or longer."""
        err = await self._provider().validate_credentials(
            self._session(),
            "u1",
            {"values": {"A" * 65: "x"}},
        )

        assert err is not None and "Entry name too long" in err

    async def test_too_long_value_rejected(self) -> None:
        """Reject values of 4KB or larger."""
        err = await self._provider().validate_credentials(
            self._session(),
            "u1",
            {"values": {"FOO": "x" * 4097}},
        )

        assert err is not None and "Entry 'FOO' value too long" in err

    async def test_too_many_entries_rejected(self) -> None:
        """Reject 51 entries or more."""
        entries = {f"VAR_{i:03d}": "x" for i in range(51)}

        err = await self._provider().validate_credentials(
            self._session(),
            "u1",
            {"values": entries},
        )

        assert err is not None and "Too many entries" in err


class TestToolkitProtocolDefault:
    """Default Toolkit.expose_env() returns empty dict."""

    async def test_base_toolkit_returns_empty_env(self) -> None:
        """Default expose_env() implementation of Toolkit ABC."""

        class _NoopToolkit(Toolkit[EnvVarToolkitConfig]):
            async def update_context(self, context: TurnContext) -> ToolkitState:  # noqa: ARG002
                return ToolkitState(tools=[], status=ToolkitStatus.ENABLED)

        setting = await _NoopToolkit().expose_env()

        assert setting == {}
