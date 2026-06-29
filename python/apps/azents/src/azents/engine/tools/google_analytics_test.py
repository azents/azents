"""Google Analytics Native Toolkit unit tests."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.analytics.data_v1beta import (
    DimensionHeader,
    DimensionValue,
    MetricHeader,
    MetricValue,
    Row,
    RunReportResponse,
)

from azents.core.tools import (
    GoogleAnalyticsToolkitConfig,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.tools.google_analytics import (
    GoogleAnalyticsToolkit,
    GoogleAnalyticsToolkitProvider,
    format_report,
)
from azents.engine.tools.google_analytics_api import (
    GoogleAnalyticsApiClient,
)


def _make_context() -> TurnContext:
    """Create TurnContext for tests."""
    return TurnContext(
        user_id="test-user",
        workspace_id="test-workspace",
        model="claude-sonnet-4-20250514",
        run_id="test-run",
        publish_event=AsyncMock(),
    )


def _make_api_client() -> GoogleAnalyticsApiClient:
    """Create API client with mock SDK client."""
    return GoogleAnalyticsApiClient(
        data_client=AsyncMock(),
        admin_client=AsyncMock(),
    )


def _make_toolkit(
    default_property_id: str | None = None,
    api_client: GoogleAnalyticsApiClient | None = None,
) -> GoogleAnalyticsToolkit:
    """Create Toolkit for tests."""
    return GoogleAnalyticsToolkit(
        config=GoogleAnalyticsToolkitConfig(
            default_property_id=default_property_id,
        ),
        api_client=api_client or _make_api_client(),
    )


# -------------------------------------------------------------------
# Toolkit — update_context
# -------------------------------------------------------------------


class TestGoogleAnalyticsToolkitUpdateContext:
    """update_context() method tests."""

    @pytest.mark.asyncio
    async def test_returns_seven_tools(self) -> None:
        """Seven tools are returned."""
        toolkit = _make_toolkit()
        state = await toolkit.update_context(_make_context())

        assert state.status == ToolkitStatus.ENABLED
        assert len(state.tools) == 7

    @pytest.mark.asyncio
    async def test_tool_names(self) -> None:
        """Correct tool names are returned."""
        toolkit = _make_toolkit()
        state = await toolkit.update_context(_make_context())

        names = {t.spec.name for t in state.tools}
        assert names == {
            "run_report",
            "run_realtime_report",
            "get_custom_dimensions_and_metrics",
            "get_account_summaries",
            "get_property_details",
            "list_google_ads_links",
            "list_property_annotations",
        }


# -------------------------------------------------------------------
# Toolkit — prompt
# -------------------------------------------------------------------


class TestGoogleAnalyticsToolkitPrompt:
    """default_property_id prompt tests."""

    @pytest.mark.asyncio
    async def test_prompt_with_property_id(self) -> None:
        """default_property_id is included in prompt when set."""
        toolkit = _make_toolkit(default_property_id="123456")
        await toolkit.update_context(_make_context())
        assert "123456" in (await toolkit.get_static_prompt(_make_context()))

    @pytest.mark.asyncio
    async def test_prompt_without_property_id(self) -> None:
        """Prompt is empty when default_property_id is absent."""
        toolkit = _make_toolkit()
        await toolkit.update_context(_make_context())
        assert (await toolkit.get_static_prompt(_make_context())) == ""


# -------------------------------------------------------------------
# Provider — validate_credentials
# -------------------------------------------------------------------


class TestGoogleAnalyticsProviderValidation:
    """validate_credentials() method tests."""

    @pytest.mark.asyncio
    async def test_valid_sa_key(self) -> None:
        """Valid SA Key passes."""
        provider = GoogleAnalyticsToolkitProvider()
        result = await provider.validate_credentials(
            session=AsyncMock(),
            user_id="user",
            credentials={
                "service_account_key": {
                    "type": "service_account",
                    "project_id": "test",
                    "private_key": "key",
                    "client_email": "test@test.iam.gserviceaccount.com",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_credentials(self) -> None:
        """Return error message when credentials is None."""
        provider = GoogleAnalyticsToolkitProvider()
        result = await provider.validate_credentials(
            session=AsyncMock(),
            user_id="user",
            credentials=None,
        )
        assert result is not None
        assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_fields(self) -> None:
        """Return error message when required field is missing."""
        provider = GoogleAnalyticsToolkitProvider()
        result = await provider.validate_credentials(
            session=AsyncMock(),
            user_id="user",
            credentials={
                "service_account_key": {
                    "type": "service_account",
                }
            },
        )
        assert result is not None
        assert "missing" in result.lower()


# -------------------------------------------------------------------
# Provider — test_connection
# -------------------------------------------------------------------


class TestGoogleAnalyticsProviderTestConnection:
    """test_connection() method tests."""

    @pytest.mark.asyncio
    async def test_no_credentials(self) -> None:
        """Return failure when credentials is absent."""
        provider = GoogleAnalyticsToolkitProvider()
        result = await provider.test_connection(
            config=GoogleAnalyticsToolkitConfig(),
            credentials_json=None,
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_invalid_credentials(self) -> None:
        """Return failure when JSON is invalid."""
        provider = GoogleAnalyticsToolkitProvider()
        result = await provider.test_connection(
            config=GoogleAnalyticsToolkitConfig(),
            credentials_json="invalid-json",
        )
        assert not result.success


# -------------------------------------------------------------------
# Report formatter
# -------------------------------------------------------------------


class TestFormatReport:
    """format_report() tests."""

    def test_empty_response(self) -> None:
        """Return 'No data' message when no rows exist."""
        resp = RunReportResponse(rows=[], row_count=0)
        assert "No data" in format_report(resp)

    def test_basic_report(self) -> None:
        """Default report is converted to markdown table."""
        resp = RunReportResponse(
            dimension_headers=[DimensionHeader(name="country")],
            metric_headers=[MetricHeader(name="activeUsers")],
            rows=[
                Row(
                    dimension_values=[DimensionValue(value="South Korea")],
                    metric_values=[MetricValue(value="100")],
                )
            ],
            row_count=1,
        )
        result = format_report(resp)
        assert "country" in result
        assert "activeUsers" in result
        assert "South Korea" in result
        assert "100" in result

    def test_no_dimensions(self) -> None:
        """Report without dimension is also formatted."""
        resp = RunReportResponse(
            dimension_headers=[],
            metric_headers=[MetricHeader(name="sessions")],
            rows=[
                Row(
                    dimension_values=[],
                    metric_values=[MetricValue(value="500")],
                )
            ],
            row_count=1,
        )
        result = format_report(resp)
        assert "sessions" in result
        assert "500" in result


# -------------------------------------------------------------------
# Tool execution
# -------------------------------------------------------------------


class TestToolExecution:
    """Tool execution tests."""

    @pytest.mark.asyncio
    async def test_run_report_tool(self) -> None:
        """run_report tool runs correctly."""
        api = _make_api_client()
        mock_resp = RunReportResponse(
            dimension_headers=[DimensionHeader(name="date")],
            metric_headers=[MetricHeader(name="sessions")],
            rows=[
                Row(
                    dimension_values=[DimensionValue(value="20260401")],
                    metric_values=[MetricValue(value="42")],
                )
            ],
            row_count=1,
        )
        api._data.run_report = AsyncMock(return_value=mock_resp)  # pyright: ignore[reportPrivateUsage]  # directly set mock SDK client in tests

        toolkit = _make_toolkit(api_client=api)
        state = await toolkit.update_context(_make_context())

        run_report_tool = next(t for t in state.tools if t.spec.name == "run_report")
        result = await run_report_tool.handler(
            json.dumps(
                {
                    "property_id": "123456",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-31",
                    "metrics": ["sessions"],
                    "dimensions": ["date"],
                }
            )
        )

        assert isinstance(result, str)
        assert "42" in result
        assert "sessions" in result

    @pytest.mark.asyncio
    async def test_get_account_summaries_tool(self) -> None:
        """get_account_summaries tool runs correctly."""
        api = _make_api_client()

        mock_account = MagicMock()
        mock_account.name = "accountSummaries/12345"
        mock_account.account = "accounts/12345"
        mock_account.display_name = "Test Account"
        mock_account.property_summaries = []

        mock_pager = _AsyncIteratorMock([mock_account])
        api._admin.list_account_summaries = AsyncMock(  # pyright: ignore[reportPrivateUsage]  # directly set mock SDK client in tests
            return_value=mock_pager,
        )

        toolkit = _make_toolkit(api_client=api)
        state = await toolkit.update_context(_make_context())

        tool = next(t for t in state.tools if t.spec.name == "get_account_summaries")
        result = await tool.handler(json.dumps({}))

        assert isinstance(result, str)
        assert "Test Account" in result


# -------------------------------------------------------------------
# AsyncIterator mock helper
# -------------------------------------------------------------------


class _AsyncIteratorMock:
    """Async pager mock."""

    def __init__(self, items: list[object]) -> None:
        self._items = items
        self._index = 0

    def __aiter__(self) -> _AsyncIteratorMock:
        self._index = 0
        return self

    async def __anext__(self) -> object:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item
