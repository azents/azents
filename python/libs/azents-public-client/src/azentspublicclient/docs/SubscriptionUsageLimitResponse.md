# SubscriptionUsageLimitResponse

Normalized public subscription usage window.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**label** | **str** |  | 
**used_percent** | **float** |  | 
**window_minutes** | **int** |  | 
**resets_at** | **datetime** |  | 
**primary** | **bool** |  | 

## Example

```python
from azentspublicclient.models.subscription_usage_limit_response import SubscriptionUsageLimitResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SubscriptionUsageLimitResponse from a JSON string
subscription_usage_limit_response_instance = SubscriptionUsageLimitResponse.from_json(json)
# print the JSON string representation of the object
print(SubscriptionUsageLimitResponse.to_json())

# convert the object into a dict
subscription_usage_limit_response_dict = subscription_usage_limit_response_instance.to_dict()
# create an instance of SubscriptionUsageLimitResponse from a dict
subscription_usage_limit_response_from_dict = SubscriptionUsageLimitResponse.from_dict(subscription_usage_limit_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


