# ResponseLlmProviderIntegrationV1GetSubscriptionUsage


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  |
**integration_id** | **str** |  |
**provider** | **str** |  |
**fetched_at** | **datetime** |  |
**plan_label** | **str** |  |
**limits** | [**List[SubscriptionUsageLimitResponse]**](SubscriptionUsageLimitResponse.md) |  |
**financial_details** | [**SubscriptionUsageAvailableResponseFinancialDetails**](SubscriptionUsageAvailableResponseFinancialDetails.md) |  |
**url** | **str** |  |
**message** | **str** |  |
**reason** | [**SubscriptionUsageUnavailableReason**](SubscriptionUsageUnavailableReason.md) |  |
**retryable** | **bool** |  |

## Example

```python
from azentspublicclient.models.response_llm_provider_integration_v1_get_subscription_usage import ResponseLlmProviderIntegrationV1GetSubscriptionUsage

# TODO update the JSON string below
json = "{}"
# create an instance of ResponseLlmProviderIntegrationV1GetSubscriptionUsage from a JSON string
response_llm_provider_integration_v1_get_subscription_usage_instance = ResponseLlmProviderIntegrationV1GetSubscriptionUsage.from_json(json)
# print the JSON string representation of the object
print(ResponseLlmProviderIntegrationV1GetSubscriptionUsage.to_json())

# convert the object into a dict
response_llm_provider_integration_v1_get_subscription_usage_dict = response_llm_provider_integration_v1_get_subscription_usage_instance.to_dict()
# create an instance of ResponseLlmProviderIntegrationV1GetSubscriptionUsage from a dict
response_llm_provider_integration_v1_get_subscription_usage_from_dict = ResponseLlmProviderIntegrationV1GetSubscriptionUsage.from_dict(response_llm_provider_integration_v1_get_subscription_usage_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
