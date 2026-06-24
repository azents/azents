# ToolkitResponse

Toolkit tool definition response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**slug** | **str** | Tool slug |
**name** | **str** | Tool name |
**description** | **str** | Tool description |
**config_schema** | **Dict[str, object]** | Configuration JSON Schema |
**system_prompt** | **str** | Definition-level system prompt |

## Example

```python
from azentspublicclient.models.toolkit_response import ToolkitResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitResponse from a JSON string
toolkit_response_instance = ToolkitResponse.from_json(json)
# print the JSON string representation of the object
print(ToolkitResponse.to_json())

# convert the object into a dict
toolkit_response_dict = toolkit_response_instance.to_dict()
# create an instance of ToolkitResponse from a dict
toolkit_response_from_dict = ToolkitResponse.from_dict(toolkit_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
