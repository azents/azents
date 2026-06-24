# ToolkitListResponse

Toolkit tool definition list response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ToolkitResponse]**](ToolkitResponse.md) |  |

## Example

```python
from azentspublicclient.models.toolkit_list_response import ToolkitListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitListResponse from a JSON string
toolkit_list_response_instance = ToolkitListResponse.from_json(json)
# print the JSON string representation of the object
print(ToolkitListResponse.to_json())

# convert the object into a dict
toolkit_list_response_dict = toolkit_list_response_instance.to_dict()
# create an instance of ToolkitListResponse from a dict
toolkit_list_response_from_dict = ToolkitListResponse.from_dict(toolkit_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
