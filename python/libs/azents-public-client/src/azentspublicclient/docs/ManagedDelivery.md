# ManagedDelivery


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**operation** | [**ExternalChannelDeliveryOperation**](ExternalChannelDeliveryOperation.md) |  | 
**status** | [**ExternalChannelDeliveryStatus**](ExternalChannelDeliveryStatus.md) |  | 
**error_kind** | **str** |  | 
**error_summary** | **str** |  | 
**attempted_at** | **datetime** |  | 
**completed_at** | **datetime** |  | 
**created_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_delivery import ManagedDelivery

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedDelivery from a JSON string
managed_delivery_instance = ManagedDelivery.from_json(json)
# print the JSON string representation of the object
print(ManagedDelivery.to_json())

# convert the object into a dict
managed_delivery_dict = managed_delivery_instance.to_dict()
# create an instance of ManagedDelivery from a dict
managed_delivery_from_dict = ManagedDelivery.from_dict(managed_delivery_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


