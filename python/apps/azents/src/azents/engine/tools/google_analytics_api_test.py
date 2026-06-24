"""GoogleAnalyticsApiClient unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from google.analytics.data_v1beta import (
    DateRange,
    DimensionHeader,
    DimensionValue,
    MetricHeader,
    MetricValue,
    Row,
    RunReportResponse,
)

from azents.engine.tools.google_analytics_api import (
    GoogleAnalyticsApiClient,
)


def _make_client(
    data_client: AsyncMock | None = None,
    admin_client: AsyncMock | None = None,
) -> GoogleAnalyticsApiClient:
    """Create API client for tests."""
    return GoogleAnalyticsApiClient(
        data_client=data_client or AsyncMock(),
        admin_client=admin_client or AsyncMock(),
    )


def _make_report_response(
    dim_names: list[str],
    metric_names: list[str],
    rows: list[tuple[list[str], list[str]]],
) -> RunReportResponse:
    """Create report response for tests."""
    return RunReportResponse(
        dimension_headers=[DimensionHeader(name=n) for n in dim_names],
        metric_headers=[MetricHeader(name=n) for n in metric_names],
        rows=[
            Row(
                dimension_values=[DimensionValue(value=v) for v in dims],
                metric_values=[MetricValue(value=v) for v in metrics],
            )
            for dims, metrics in rows
        ],
        row_count=len(rows),
    )


# -------------------------------------------------------------------
# run_report
# -------------------------------------------------------------------


class TestRunReport:
    """run_report method tests."""

    @pytest.mark.asyncio
    async def test_basic_report(self) -> None:
        """Default report request is passed correctly."""
        data_client = AsyncMock()
        data_client.run_report = AsyncMock(
            return_value=_make_report_response(
                ["country"],
                ["activeUsers"],
                [(["South Korea"], ["100"])],
            )
        )

        client = _make_client(data_client=data_client)
        result = await client.run_report(
            property_id="123456",
            date_ranges=[
                DateRange(
                    start_date="2026-03-01",
                    end_date="2026-03-31",
                )
            ],
            metrics=["activeUsers"],
            dimensions=["country"],
        )

        data_client.run_report.assert_called_once()
        assert result.row_count == 1
        assert result.rows[0].metric_values[0].value == "100"

    @pytest.mark.asyncio
    async def test_report_without_dimensions(self) -> None:
        """Report request is possible without dimensions."""
        data_client = AsyncMock()
        data_client.run_report = AsyncMock(
            return_value=_make_report_response([], ["sessions"], [([], ["500"])])
        )

        client = _make_client(data_client=data_client)
        result = await client.run_report(
            property_id="123456",
            date_ranges=[
                DateRange(
                    start_date="2026-03-01",
                    end_date="2026-03-31",
                )
            ],
            metrics=["sessions"],
        )

        assert result.row_count == 1


# -------------------------------------------------------------------
# run_realtime_report
# -------------------------------------------------------------------


class TestRunRealtimeReport:
    """run_realtime_report method tests."""

    @pytest.mark.asyncio
    async def test_realtime_report(self) -> None:
        """Realtime report is called correctly."""
        data_client = AsyncMock()
        # RunRealtimeReportResponse has same structure as RunReportResponse
        mock_resp = MagicMock()
        mock_resp.dimension_headers = []
        mock_resp.metric_headers = [MetricHeader(name="activeUsers")]
        mock_resp.rows = [
            Row(
                dimension_values=[],
                metric_values=[MetricValue(value="42")],
            )
        ]
        mock_resp.row_count = 1
        data_client.run_realtime_report = AsyncMock(return_value=mock_resp)

        client = _make_client(data_client=data_client)
        result = await client.run_realtime_report(
            property_id="123456",
            metrics=["activeUsers"],
        )

        data_client.run_realtime_report.assert_called_once()
        assert result.row_count == 1


# -------------------------------------------------------------------
# get_metadata
# -------------------------------------------------------------------


class TestGetMetadata:
    """get_metadata method tests."""

    @pytest.mark.asyncio
    async def test_get_metadata(self) -> None:
        """Metadata is fetched correctly."""
        data_client = AsyncMock()
        mock_resp = MagicMock()
        mock_dim = MagicMock()
        mock_dim.api_name = "country"
        mock_dim.ui_name = "Country"
        mock_dim.description = "Country name"
        mock_dim.category = "Geo"
        mock_resp.dimensions = [mock_dim]
        mock_resp.metrics = []
        data_client.get_metadata = AsyncMock(return_value=mock_resp)

        client = _make_client(data_client=data_client)
        result = await client.get_metadata(property_id="123456")

        assert len(result["dimensions"]) == 1  # pyright: ignore[reportArgumentType]  # dict value is list
        data_client.get_metadata.assert_called_once()


# -------------------------------------------------------------------
# Admin API
# -------------------------------------------------------------------


class TestAdminApi:
    """Admin API method tests."""

    @pytest.mark.asyncio
    async def test_get_account_summaries(self) -> None:
        """Account summary list is fetched correctly."""
        admin_client = AsyncMock()
        mock_account = MagicMock()
        mock_account.name = "accountSummaries/12345"
        mock_account.account = "accounts/12345"
        mock_account.display_name = "Test Account"
        mock_account.property_summaries = []

        # async pager mock
        mock_pager = AsyncIteratorMock([mock_account])
        admin_client.list_account_summaries = AsyncMock(return_value=mock_pager)

        client = _make_client(admin_client=admin_client)
        result = await client.get_account_summaries()

        assert len(result) == 1
        assert result[0]["displayName"] == "Test Account"

    @pytest.mark.asyncio
    async def test_get_property_details(self) -> None:
        """Property details are fetched correctly."""
        admin_client = AsyncMock()
        mock_prop = MagicMock()
        mock_prop.name = "properties/123456"
        mock_prop.display_name = "Test Property"
        mock_prop.property_type = "PROPERTY_TYPE_ORDINARY"
        mock_prop.industry_category = "OTHER"
        mock_prop.time_zone = "Asia/Seoul"
        mock_prop.currency_code = "KRW"
        mock_prop.service_level = "STANDARD"
        mock_prop.create_time = "2024-01-01"
        mock_prop.update_time = "2024-06-01"
        admin_client.get_property = AsyncMock(return_value=mock_prop)

        client = _make_client(admin_client=admin_client)
        result = await client.get_property_details("123456")

        assert result["displayName"] == "Test Property"
        assert result["timeZone"] == "Asia/Seoul"

    @pytest.mark.asyncio
    async def test_list_google_ads_links(self) -> None:
        """Ads link list is fetched correctly."""
        admin_client = AsyncMock()
        mock_pager = AsyncIteratorMock([])
        admin_client.list_google_ads_links = AsyncMock(return_value=mock_pager)

        client = _make_client(admin_client=admin_client)
        result = await client.list_google_ads_links("123456")

        assert result == []

    @pytest.mark.asyncio
    async def test_list_key_events(self) -> None:
        """Key Events are fetched correctly."""
        admin_client = AsyncMock()
        mock_event = MagicMock()
        mock_event.name = "properties/123/keyEvents/1"
        mock_event.event_name = "purchase"
        mock_event.create_time = "2024-01-01"
        mock_event.deletable = True
        mock_event.counting_method = "ONCE_PER_EVENT"
        mock_pager = AsyncIteratorMock([mock_event])
        admin_client.list_key_events = AsyncMock(return_value=mock_pager)

        client = _make_client(admin_client=admin_client)
        result = await client.list_key_events("123456")

        assert len(result) == 1
        assert result[0]["eventName"] == "purchase"


# -------------------------------------------------------------------
# AsyncIterator mock helper
# -------------------------------------------------------------------


class AsyncIteratorMock:
    """Async pager mock."""

    def __init__(self, items: list[object]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncIteratorMock:
        self._index = 0
        return self

    async def __anext__(self) -> object:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item
