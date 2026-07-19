# SubscriptionUsageExternalResponse

Public provider-managed subscription usage response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  |
**integration_id** | **str** |  |
**provider** | **str** |  |
**fetched_at** | **datetime** |  |
**url** | **str** |  |
**message** | **str** |  |

## Example

```python
from azentspublicclient.models.subscription_usage_external_response import SubscriptionUsageExternalResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SubscriptionUsageExternalResponse from a JSON string
subscription_usage_external_response_instance = SubscriptionUsageExternalResponse.from_json(json)
# print the JSON string representation of the object
print(SubscriptionUsageExternalResponse.to_json())

# convert the object into a dict
subscription_usage_external_response_dict = subscription_usage_external_response_instance.to_dict()
# create an instance of SubscriptionUsageExternalResponse from a dict
subscription_usage_external_response_from_dict = SubscriptionUsageExternalResponse.from_dict(subscription_usage_external_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
