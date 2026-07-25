# ManagedMultiConnectionListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ManagedMultiConnection]**](ManagedMultiConnection.md) |  | 

## Example

```python
from azentspublicclient.models.managed_multi_connection_list_response import ManagedMultiConnectionListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedMultiConnectionListResponse from a JSON string
managed_multi_connection_list_response_instance = ManagedMultiConnectionListResponse.from_json(json)
# print the JSON string representation of the object
print(ManagedMultiConnectionListResponse.to_json())

# convert the object into a dict
managed_multi_connection_list_response_dict = managed_multi_connection_list_response_instance.to_dict()
# create an instance of ManagedMultiConnectionListResponse from a dict
managed_multi_connection_list_response_from_dict = ManagedMultiConnectionListResponse.from_dict(managed_multi_connection_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


