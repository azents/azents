"""Google Analytics Toolkit.

Native Toolkit that calls GA4 Data API / Admin API with official Google SDK.
Create google.oauth2 Credentials from SA Key and pass to SDK client.
"""

import json
import logging
from textwrap import dedent
from typing import ClassVar

from google.analytics.admin_v1beta import AnalyticsAdminServiceAsyncClient
from google.analytics.data_v1beta import (
    BetaAnalyticsDataAsyncClient,
    DateRange,
    RunReportResponse,
)
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import (
    GoogleAnalyticsToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionTool
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.gcp import GcpSecrets
from azents.engine.tools.google_analytics_api import (
    GoogleAnalyticsApiClient,
    create_credentials,
)

logger = logging.getLogger(__name__)

_SA_KEY_REQUIRED_FIELDS = {
    "type",
    "project_id",
    "private_key",
    "client_email",
    "token_uri",
}


# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------


class RunReportInput(BaseModel):
    """run_report tool input."""

    property_id: str = Field(
        description="GA4 property ID (e.g. 123456789)",
    )
    start_date: str = Field(
        description=(
            "Start date (YYYY-MM-DD or relative: 'yesterday', '7daysAgo', '30daysAgo')"
        ),
    )
    end_date: str = Field(
        description="End date (YYYY-MM-DD or 'today', 'yesterday')",
    )
    metrics: list[str] = Field(
        description=(
            "Metric names (e.g. ['activeUsers', 'sessions', 'screenPageViews'])"
        ),
    )
    dimensions: list[str] = Field(
        default=[],
        description="Dimension names (e.g. ['country', 'city'])",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Max rows to return",
    )


class RunRealtimeReportInput(BaseModel):
    """run_realtime_report tool input."""

    property_id: str = Field(description="GA4 property ID")
    metrics: list[str] = Field(
        description="Metric names (e.g. ['activeUsers'])",
    )
    dimensions: list[str] = Field(
        default=[],
        description="Dimension names (e.g. ['country'])",
    )
    limit: int = Field(default=100, ge=1, le=10000, description="Max rows to return")


class GetCustomDimensionsAndMetricsInput(BaseModel):
    """get_custom_dimensions_and_metrics tool input."""

    property_id: str = Field(description="GA4 property ID")


class GetAccountSummariesInput(BaseModel):
    """get_account_summaries tool input. No parameters."""


class GetPropertyDetailsInput(BaseModel):
    """get_property_details tool input."""

    property_id: str = Field(description="GA4 property ID")


class ListGoogleAdsLinksInput(BaseModel):
    """list_google_ads_links tool input."""

    property_id: str = Field(description="GA4 property ID")


class ListPropertyAnnotationsInput(BaseModel):
    """list_property_annotations tool input."""

    property_id: str = Field(description="GA4 property ID")


# ---------------------------------------------------------------------------
# Tool factory functions
# ---------------------------------------------------------------------------


def _make_run_report_tool(
    api: GoogleAnalyticsApiClient,
    default_property_id: str | None,
) -> FunctionTool:
    """run_report Create tool."""

    async def run_report(args: RunReportInput) -> str:
        """Run a GA4 standard report with dimensions, metrics, and date ranges."""
        pid = args.property_id or default_property_id
        if not pid:
            return "Error: property_id is required"
        result = await api.run_report(
            property_id=pid,
            date_ranges=[
                DateRange(
                    start_date=args.start_date,
                    end_date=args.end_date,
                )
            ],
            metrics=args.metrics,
            dimensions=args.dimensions or None,
            limit=args.limit,
        )
        return format_report(result)

    return make_tool(run_report, input_model=RunReportInput)


def _make_run_realtime_report_tool(
    api: GoogleAnalyticsApiClient,
    default_property_id: str | None,
) -> FunctionTool:
    """run_realtime_report Create tool."""

    async def run_realtime_report(args: RunRealtimeReportInput) -> str:
        """Run a GA4 realtime report showing live user activity."""
        pid = args.property_id or default_property_id
        if not pid:
            return "Error: property_id is required"
        result = await api.run_realtime_report(
            property_id=pid,
            metrics=args.metrics,
            dimensions=args.dimensions or None,
            limit=args.limit,
        )
        return format_report(result)

    return make_tool(run_realtime_report, input_model=RunRealtimeReportInput)


def _make_get_custom_dimensions_and_metrics_tool(
    api: GoogleAnalyticsApiClient,
    default_property_id: str | None,
) -> FunctionTool:
    """get_custom_dimensions_and_metrics Create tool."""

    async def get_custom_dimensions_and_metrics(
        args: GetCustomDimensionsAndMetricsInput,
    ) -> str:
        """Get available dimensions and metrics for a GA4 property."""  # noqa: E501
        pid = args.property_id or default_property_id
        if not pid:
            return "Error: property_id is required"
        result = await api.get_metadata(property_id=pid)
        return json.dumps(result, indent=2, ensure_ascii=False)

    return make_tool(
        get_custom_dimensions_and_metrics,
        input_model=GetCustomDimensionsAndMetricsInput,
    )


def _make_get_account_summaries_tool(
    api: GoogleAnalyticsApiClient,
) -> FunctionTool:
    """get_account_summaries Create tool."""

    async def get_account_summaries(
        _args: GetAccountSummariesInput,
    ) -> str:
        """List all GA4 accounts and properties accessible by the service account."""  # noqa: E501
        result = await api.get_account_summaries()
        return json.dumps(result, indent=2, ensure_ascii=False)

    return make_tool(
        get_account_summaries,
        input_model=GetAccountSummariesInput,
    )


def _make_get_property_details_tool(
    api: GoogleAnalyticsApiClient,
    default_property_id: str | None,
) -> FunctionTool:
    """get_property_details Create tool."""

    async def get_property_details(args: GetPropertyDetailsInput) -> str:
        """Get detailed information about a GA4 property."""
        pid = args.property_id or default_property_id
        if not pid:
            return "Error: property_id is required"
        result = await api.get_property_details(property_id=pid)
        return json.dumps(result, indent=2, ensure_ascii=False)

    return make_tool(get_property_details, input_model=GetPropertyDetailsInput)


def _make_list_google_ads_links_tool(
    api: GoogleAnalyticsApiClient,
    default_property_id: str | None,
) -> FunctionTool:
    """list_google_ads_links Create tool."""

    async def list_google_ads_links(args: ListGoogleAdsLinksInput) -> str:
        """List Google Ads connections for a GA4 property."""
        pid = args.property_id or default_property_id
        if not pid:
            return "Error: property_id is required"
        result = await api.list_google_ads_links(property_id=pid)
        return json.dumps(result, indent=2, ensure_ascii=False)

    return make_tool(list_google_ads_links, input_model=ListGoogleAdsLinksInput)


def _make_list_property_annotations_tool(
    api: GoogleAnalyticsApiClient,
    default_property_id: str | None,
) -> FunctionTool:
    """list_property_annotations Create tool."""

    async def list_property_annotations(
        args: ListPropertyAnnotationsInput,
    ) -> str:
        """List key events (annotations) for a GA4 property."""
        pid = args.property_id or default_property_id
        if not pid:
            return "Error: property_id is required"
        result = await api.list_key_events(property_id=pid)
        return json.dumps(result, indent=2, ensure_ascii=False)

    return make_tool(
        list_property_annotations, input_model=ListPropertyAnnotationsInput
    )


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------


def format_report(resp: RunReportResponse) -> str:
    """Convert GA4 report response to readable text."""
    if not resp.rows:
        return "No data returned."

    dim_names = [h.name for h in resp.dimension_headers]
    metric_names = [h.name for h in resp.metric_headers]
    all_headers = dim_names + metric_names

    if not all_headers:
        return "No data returned."

    table_rows: list[list[str]] = []
    for row in resp.rows:
        cells = [v.value for v in row.dimension_values] + [
            v.value for v in row.metric_values
        ]
        table_rows.append(cells)

    lines = [f"Report Results ({resp.row_count} rows):"]
    lines.append("| " + " | ".join(all_headers) + " |")
    lines.append("| " + " | ".join("---" for _ in all_headers) + " |")
    for cells in table_rows:
        padded = cells + [""] * (len(all_headers) - len(cells))
        lines.append("| " + " | ".join(padded[: len(all_headers)]) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Toolkit
# ---------------------------------------------------------------------------


class GoogleAnalyticsToolkit(Toolkit[GoogleAnalyticsToolkitConfig]):
    """GA4 Native Toolkit execution instance.

    :param config: GA4 toolkit settings
    :param api_client: GA4 SDK API client
    """

    def __init__(
        self,
        *,
        config: GoogleAnalyticsToolkitConfig,
        api_client: GoogleAnalyticsApiClient,
    ) -> None:
        self._config = config
        self._api = api_client

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return seven GA4 native tools."""
        default_pid = self._config.default_property_id

        tools: list[FunctionTool] = [
            _make_run_report_tool(self._api, default_pid),
            _make_run_realtime_report_tool(self._api, default_pid),
            _make_get_custom_dimensions_and_metrics_tool(self._api, default_pid),
            _make_get_account_summaries_tool(self._api),
            _make_get_property_details_tool(self._api, default_pid),
            _make_list_google_ads_links_tool(self._api, default_pid),
            _make_list_property_annotations_tool(self._api, default_pid),
        ]

        prompt = ""
        if default_pid:
            prompt = f"Default GA4 Property: {default_pid}"

        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=tools,
            prompt=prompt,
        )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class GoogleAnalyticsToolkitProvider(
    ToolkitProvider[GoogleAnalyticsToolkitConfig],
):
    """Google Analytics Toolkit Provider.

    SA Key -> google.oauth2.Credentials -> SDK client ->
    GoogleAnalyticsApiClient → GoogleAnalyticsToolkit.
    """

    slug: ClassVar[str] = "google_analytics"
    name: ClassVar[str] = "Google Analytics"
    description: ClassVar[str] = (
        "Google Analytics 4 — reports, realtime data, account management"
    )
    system_prompt: ClassVar[str] = dedent("""\
        You have access to Google Analytics 4 tools.
        Use get_account_summaries to discover available properties.
        Use run_report for standard reports with dimensions, metrics,
        and date ranges.
        Use run_realtime_report for live data.""")
    config_model: ClassVar[type[BaseModel]] = GoogleAnalyticsToolkitConfig

    async def resolve(
        self,
        config: GoogleAnalyticsToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[GoogleAnalyticsToolkitConfig]:
        """SA Key validation -> SDK Credentials -> API Client -> Toolkit."""
        if context.credentials_json is None:
            msg = "Google Analytics toolkit requires Service Account Key"
            raise ValueError(msg)

        secrets = GcpSecrets.model_validate_json(context.credentials_json)
        credentials = create_credentials(secrets.service_account_key)

        data_client = BetaAnalyticsDataAsyncClient(credentials=credentials)
        admin_client = AnalyticsAdminServiceAsyncClient(credentials=credentials)

        api_client = GoogleAnalyticsApiClient(
            data_client=data_client,
            admin_client=admin_client,
        )

        return GoogleAnalyticsToolkit(
            config=config,
            api_client=api_client,
        )

    async def validate_credentials(
        self,
        session: AsyncSession,
        user_id: str,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Validate Service Account Key JSON structure."""
        if credentials is None:
            return "Service Account Key is required"

        try:
            secrets = GcpSecrets.model_validate(credentials)
        except ValidationError as e:
            return f"Invalid credentials format: {e}"

        key = secrets.service_account_key
        missing = _SA_KEY_REQUIRED_FIELDS - key.keys()
        if missing:
            return f"Service Account Key missing fields: {', '.join(sorted(missing))}"

        if key.get("type") != "service_account":
            return f"Expected type 'service_account', got '{key.get('type')}'"

        return None

    async def test_connection(
        self,
        config: GoogleAnalyticsToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Test connection with actual API call."""
        if not credentials_json:
            return TestConnectionResult(
                success=False,
                message="No credentials provided",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        try:
            secrets = GcpSecrets.model_validate_json(credentials_json)
        except ValidationError as e:
            return TestConnectionResult(
                success=False,
                message=f"Invalid credentials: {e}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        credentials = create_credentials(secrets.service_account_key)

        try:
            data_client = BetaAnalyticsDataAsyncClient(credentials=credentials)
            admin_client = AnalyticsAdminServiceAsyncClient(
                credentials=credentials,
            )
            api = GoogleAnalyticsApiClient(
                data_client=data_client,
                admin_client=admin_client,
            )
            summaries = await api.get_account_summaries()
            count = len(summaries)
            return TestConnectionResult(
                success=True,
                message=f"Connected successfully. Found {count} account(s).",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
        except Exception:
            logger.exception("GA4 connection test failed")
            return TestConnectionResult(
                success=False,
                message="Connection test failed",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
