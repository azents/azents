# ManagedBinding


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**agent_session_id** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**resource_type** | **str** |  | 
**resource_label** | **str** |  | 
**status** | [**ExternalChannelBindingStatus**](ExternalChannelBindingStatus.md) |  | 
**activation_status** | [**ExternalChannelBindingActivationStatus**](ExternalChannelBindingActivationStatus.md) |  | 
**truncated_message_count** | **int** |  | 
**truncated_size** | **int** |  | 
**connected_at** | **datetime** |  | 
**disconnected_at** | **datetime** |  | 
**disconnect_reason** | **str** |  | 
**latest_activity_at** | **datetime** |  | 
**work** | [**ManagedWork**](ManagedWork.md) |  | 
**deliveries** | [**List[ManagedDelivery]**](ManagedDelivery.md) |  | 

## Example

```python
from azentspublicclient.models.managed_binding import ManagedBinding

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedBinding from a JSON string
managed_binding_instance = ManagedBinding.from_json(json)
# print the JSON string representation of the object
print(ManagedBinding.to_json())

# convert the object into a dict
managed_binding_dict = managed_binding_instance.to_dict()
# create an instance of ManagedBinding from a dict
managed_binding_from_dict = ManagedBinding.from_dict(managed_binding_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


