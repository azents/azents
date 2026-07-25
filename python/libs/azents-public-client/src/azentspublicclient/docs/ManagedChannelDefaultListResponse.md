# ManagedChannelDefaultListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ManagedChannelDefault]**](ManagedChannelDefault.md) |  | 

## Example

```python
from azentspublicclient.models.managed_channel_default_list_response import ManagedChannelDefaultListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedChannelDefaultListResponse from a JSON string
managed_channel_default_list_response_instance = ManagedChannelDefaultListResponse.from_json(json)
# print the JSON string representation of the object
print(ManagedChannelDefaultListResponse.to_json())

# convert the object into a dict
managed_channel_default_list_response_dict = managed_channel_default_list_response_instance.to_dict()
# create an instance of ManagedChannelDefaultListResponse from a dict
managed_channel_default_list_response_from_dict = ManagedChannelDefaultListResponse.from_dict(managed_channel_default_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


