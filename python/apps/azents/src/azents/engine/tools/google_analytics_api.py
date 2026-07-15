"""Google Analytics 4 SDK client.

Call GA4 Data API v1beta + Admin API v1beta with official Google SDK.
Create Credentials from SA Key JSON and pass to SDK client.
"""

import logging
from typing import Any

from google.analytics.admin_v1beta import (
    AnalyticsAdminServiceAsyncClient,
    GetPropertyRequest,
    ListAccountSummariesRequest,
    ListGoogleAdsLinksRequest,
    ListKeyEventsRequest,
)
from google.analytics.data_v1beta import (
    BetaAnalyticsDataAsyncClient,
    DateRange,
    Dimension,
    GetMetadataRequest,
    Metric,
    RunRealtimeReportRequest,
    RunReportRequest,
    RunReportResponse,
)
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# GA4 read-only scope
GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def create_credentials(
    service_account_key: dict[str, Any],
) -> Credentials:
    """Create Credentials from SA Key JSON dict."""
    return Credentials.from_service_account_info(
        service_account_key,
        scopes=GA4_SCOPES,
    )


class GoogleAnalyticsApiClient:
    """GA4 Data API + Admin API async client.

    :param data_client: Data API async client
    :param admin_client: Admin API async client
    """

    def __init__(
        self,
        data_client: BetaAnalyticsDataAsyncClient,
        admin_client: AnalyticsAdminServiceAsyncClient,
    ) -> None:
        self.data = data_client
        self.admin = admin_client

    # -----------------------------------------------------------------------
    # Data API
    # -----------------------------------------------------------------------

    async def run_report(
        self,
        property_id: str,
        date_ranges: list[DateRange],
        metrics: list[str],
        dimensions: list[str] | None = None,
        limit: int = 10000,
        offset: int = 0,
    ) -> RunReportResponse:
        """Run GA4 standard report."""
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=date_ranges,
            metrics=[Metric(name=m) for m in metrics],
            dimensions=([Dimension(name=d) for d in dimensions] if dimensions else []),
            limit=limit,
            offset=offset,
        )
        return await self.data.run_report(request=request)

    async def run_realtime_report(
        self,
        property_id: str,
        metrics: list[str],
        dimensions: list[str] | None = None,
        limit: int = 10000,
    ) -> RunReportResponse:
        """Run GA4 realtime report."""
        request = RunRealtimeReportRequest(
            property=f"properties/{property_id}",
            metrics=[Metric(name=m) for m in metrics],
            dimensions=([Dimension(name=d) for d in dimensions] if dimensions else []),
            limit=limit,
        )
        resp = await self.data.run_realtime_report(request=request)
        # Return RunRealtimeReportResponse unified as RunReportResponse
        # Same structure: dimension_headers, metric_headers, rows, row_count
        return RunReportResponse(
            dimension_headers=list(resp.dimension_headers),
            metric_headers=list(resp.metric_headers),
            rows=list(resp.rows),
            row_count=resp.row_count,
        )

    async def get_metadata(self, property_id: str) -> dict[str, object]:
        """Fetch custom dimension/metric metadata for GA4 property."""
        request = GetMetadataRequest(
            name=f"properties/{property_id}/metadata",
        )
        resp = await self.data.get_metadata(request=request)

        # Convert Metadata response to dict
        dimensions = [
            {
                "apiName": d.api_name,
                "uiName": d.ui_name,
                "description": d.description,
                "category": d.category,
            }
            for d in resp.dimensions
        ]
        metrics = [
            {
                "apiName": m.api_name,
                "uiName": m.ui_name,
                "description": m.description,
                "category": m.category,
                "type": str(m.type_),
            }
            for m in resp.metrics
        ]
        return {"dimensions": dimensions, "metrics": metrics}

    # -----------------------------------------------------------------------
    # Admin API
    # -----------------------------------------------------------------------

    async def get_account_summaries(
        self,
    ) -> list[dict[str, object]]:
        """Fetch GA4 account/property summary list."""
        pager = await self.admin.list_account_summaries(
            request=ListAccountSummariesRequest(page_size=200),
        )

        summaries: list[dict[str, object]] = []
        async for account in pager:
            properties = [
                {
                    "property": ps.property,
                    "displayName": ps.display_name,
                }
                for ps in account.property_summaries
            ]
            summaries.append(
                {
                    "name": account.name,
                    "account": account.account,
                    "displayName": account.display_name,
                    "propertySummaries": properties,
                }
            )
        return summaries

    async def get_property_details(self, property_id: str) -> dict[str, object]:
        """Fetch GA4 property details."""
        resp = await self.admin.get_property(
            request=GetPropertyRequest(
                name=f"properties/{property_id}",
            ),
        )
        return {
            "name": resp.name,
            "displayName": resp.display_name,
            "propertyType": str(resp.property_type),
            "industryCategory": str(resp.industry_category),
            "timeZone": resp.time_zone,
            "currencyCode": resp.currency_code,
            "serviceLevel": str(resp.service_level),
            "createTime": str(resp.create_time),
            "updateTime": str(resp.update_time),
        }

    async def list_google_ads_links(self, property_id: str) -> list[dict[str, object]]:
        """Fetch Google Ads link list for GA4 property."""
        pager = await self.admin.list_google_ads_links(
            request=ListGoogleAdsLinksRequest(
                parent=f"properties/{property_id}",
                page_size=200,
            ),
        )

        links: list[dict[str, object]] = []
        async for link in pager:
            links.append(
                {
                    "name": link.name,
                    "customerId": link.customer_id,
                    "canManageClients": link.can_manage_clients,
                    "createTime": str(link.create_time),
                    "updateTime": str(link.update_time),
                }
            )
        return links

    async def list_key_events(self, property_id: str) -> list[dict[str, object]]:
        """Fetch Key Events (annotations) list for GA4 property."""
        pager = await self.admin.list_key_events(
            request=ListKeyEventsRequest(
                parent=f"properties/{property_id}",
                page_size=200,
            ),
        )

        events: list[dict[str, object]] = []
        async for event in pager:
            events.append(
                {
                    "name": event.name,
                    "eventName": event.event_name,
                    "createTime": str(event.create_time),
                    "deletable": event.deletable,
                    "countingMethod": str(event.counting_method),
                }
            )
        return events
