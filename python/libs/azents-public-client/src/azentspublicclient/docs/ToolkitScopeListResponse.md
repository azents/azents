# ToolkitScopeListResponse

ToolkitScope list response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ToolkitScopeResponse]**](ToolkitScopeResponse.md) |  | 

## Example

```python
from azentspublicclient.models.toolkit_scope_list_response import ToolkitScopeListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitScopeListResponse from a JSON string
toolkit_scope_list_response_instance = ToolkitScopeListResponse.from_json(json)
# print the JSON string representation of the object
print(ToolkitScopeListResponse.to_json())

# convert the object into a dict
toolkit_scope_list_response_dict = toolkit_scope_list_response_instance.to_dict()
# create an instance of ToolkitScopeListResponse from a dict
toolkit_scope_list_response_from_dict = ToolkitScopeListResponse.from_dict(toolkit_scope_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


