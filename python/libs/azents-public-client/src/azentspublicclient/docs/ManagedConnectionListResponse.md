# ManagedConnectionListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ManagedConnection]**](ManagedConnection.md) |  | 

## Example

```python
from azentspublicclient.models.managed_connection_list_response import ManagedConnectionListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedConnectionListResponse from a JSON string
managed_connection_list_response_instance = ManagedConnectionListResponse.from_json(json)
# print the JSON string representation of the object
print(ManagedConnectionListResponse.to_json())

# convert the object into a dict
managed_connection_list_response_dict = managed_connection_list_response_instance.to_dict()
# create an instance of ManagedConnectionListResponse from a dict
managed_connection_list_response_from_dict = ManagedConnectionListResponse.from_dict(managed_connection_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


