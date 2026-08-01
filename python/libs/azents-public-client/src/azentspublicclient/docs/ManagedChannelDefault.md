# ManagedChannelDefault

One redacted Multi App channel default.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider_channel_id** | **str** |  | 
**route_id** | **str** |  | 
**agent_id** | **str** |  | 
**agent_name** | **str** |  | 
**status** | [**ExternalChannelChannelDefaultStatus**](ExternalChannelChannelDefaultStatus.md) |  | 
**configured_by_user_id** | **str** |  | 
**configured_by_principal_id** | **str** |  | 
**invalidated_at** | **datetime** |  | 
**invalidation_reason** | **str** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_channel_default import ManagedChannelDefault

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedChannelDefault from a JSON string
managed_channel_default_instance = ManagedChannelDefault.from_json(json)
# print the JSON string representation of the object
print(ManagedChannelDefault.to_json())

# convert the object into a dict
managed_channel_default_dict = managed_channel_default_instance.to_dict()
# create an instance of ManagedChannelDefault from a dict
managed_channel_default_from_dict = ManagedChannelDefault.from_dict(managed_channel_default_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


