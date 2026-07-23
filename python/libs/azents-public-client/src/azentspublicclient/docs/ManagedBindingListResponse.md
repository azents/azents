# ManagedBindingListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ManagedBinding]**](ManagedBinding.md) |  | 
**grants** | [**List[ManagedGrant]**](ManagedGrant.md) |  | 

## Example

```python
from azentspublicclient.models.managed_binding_list_response import ManagedBindingListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedBindingListResponse from a JSON string
managed_binding_list_response_instance = ManagedBindingListResponse.from_json(json)
# print the JSON string representation of the object
print(ManagedBindingListResponse.to_json())

# convert the object into a dict
managed_binding_list_response_dict = managed_binding_list_response_instance.to_dict()
# create an instance of ManagedBindingListResponse from a dict
managed_binding_list_response_from_dict = ManagedBindingListResponse.from_dict(managed_binding_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


