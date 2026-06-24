# ToolkitScopeResponse

ToolkitScope response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  |
**toolkit_id** | **str** |  |
**scope_type** | [**ToolkitScopeType**](ToolkitScopeType.md) |  |
**scope_id** | **str** |  |
**created_at** | **datetime** |  |

## Example

```python
from azentspublicclient.models.toolkit_scope_response import ToolkitScopeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitScopeResponse from a JSON string
toolkit_scope_response_instance = ToolkitScopeResponse.from_json(json)
# print the JSON string representation of the object
print(ToolkitScopeResponse.to_json())

# convert the object into a dict
toolkit_scope_response_dict = toolkit_scope_response_instance.to_dict()
# create an instance of ToolkitScopeResponse from a dict
toolkit_scope_response_from_dict = ToolkitScopeResponse.from_dict(toolkit_scope_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
