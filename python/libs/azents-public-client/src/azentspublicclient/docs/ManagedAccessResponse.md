# ManagedAccessResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**grants** | [**List[ManagedGrant]**](ManagedGrant.md) |  | 
**blocks** | [**List[ManagedBlock]**](ManagedBlock.md) |  | 

## Example

```python
from azentspublicclient.models.managed_access_response import ManagedAccessResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedAccessResponse from a JSON string
managed_access_response_instance = ManagedAccessResponse.from_json(json)
# print the JSON string representation of the object
print(ManagedAccessResponse.to_json())

# convert the object into a dict
managed_access_response_dict = managed_access_response_instance.to_dict()
# create an instance of ManagedAccessResponse from a dict
managed_access_response_from_dict = ManagedAccessResponse.from_dict(managed_access_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


