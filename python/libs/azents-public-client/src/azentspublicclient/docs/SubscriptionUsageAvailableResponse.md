# SubscriptionUsageAvailableResponse

Public available subscription usage response.

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

## Example

```python
from azentspublicclient.models.subscription_usage_available_response import SubscriptionUsageAvailableResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SubscriptionUsageAvailableResponse from a JSON string
subscription_usage_available_response_instance = SubscriptionUsageAvailableResponse.from_json(json)
# print the JSON string representation of the object
print(SubscriptionUsageAvailableResponse.to_json())

# convert the object into a dict
subscription_usage_available_response_dict = subscription_usage_available_response_instance.to_dict()
# create an instance of SubscriptionUsageAvailableResponse from a dict
subscription_usage_available_response_from_dict = SubscriptionUsageAvailableResponse.from_dict(subscription_usage_available_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


