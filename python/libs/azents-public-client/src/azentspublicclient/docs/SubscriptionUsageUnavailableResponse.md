# SubscriptionUsageUnavailableResponse

Public controlled unavailable subscription usage response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  |
**integration_id** | **str** |  |
**provider** | **str** |  |
**fetched_at** | **datetime** |  |
**reason** | [**SubscriptionUsageUnavailableReason**](SubscriptionUsageUnavailableReason.md) |  |
**message** | **str** |  |
**retryable** | **bool** |  |

## Example

```python
from azentspublicclient.models.subscription_usage_unavailable_response import SubscriptionUsageUnavailableResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SubscriptionUsageUnavailableResponse from a JSON string
subscription_usage_unavailable_response_instance = SubscriptionUsageUnavailableResponse.from_json(json)
# print the JSON string representation of the object
print(SubscriptionUsageUnavailableResponse.to_json())

# convert the object into a dict
subscription_usage_unavailable_response_dict = subscription_usage_unavailable_response_instance.to_dict()
# create an instance of SubscriptionUsageUnavailableResponse from a dict
subscription_usage_unavailable_response_from_dict = SubscriptionUsageUnavailableResponse.from_dict(subscription_usage_unavailable_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
