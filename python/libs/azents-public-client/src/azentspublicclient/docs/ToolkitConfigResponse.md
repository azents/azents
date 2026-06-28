# ToolkitConfigResponse

Toolkit Config response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  |
**workspace_id** | **str** |  |
**toolkit_type** | **str** |  |
**slug** | **str** |  |
**name** | **str** |  |
**description** | **str** |  |
**config** | **Dict[str, object]** |  |
**prompt** | **str** |  |
**has_credentials** | **bool** | Whether credentials exist | [optional] [default to False]
**enabled** | **bool** |  |
**oauth_connection** | [**MCPOAuthConnectionSummaryResponse**](MCPOAuthConnectionSummaryResponse.md) |  | [optional]
**created_at** | **datetime** |  |
**updated_at** | **datetime** |  |

## Example

```python
from azentspublicclient.models.toolkit_config_response import ToolkitConfigResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitConfigResponse from a JSON string
toolkit_config_response_instance = ToolkitConfigResponse.from_json(json)
# print the JSON string representation of the object
print(ToolkitConfigResponse.to_json())

# convert the object into a dict
toolkit_config_response_dict = toolkit_config_response_instance.to_dict()
# create an instance of ToolkitConfigResponse from a dict
toolkit_config_response_from_dict = ToolkitConfigResponse.from_dict(toolkit_config_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


