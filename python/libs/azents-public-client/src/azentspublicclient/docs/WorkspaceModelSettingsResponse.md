# WorkspaceModelSettingsResponse

Workspace model settings response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**default_model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | [optional]
**default_lightweight_model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | [optional]
**effective_default_lightweight_model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | [optional]

## Example

```python
from azentspublicclient.models.workspace_model_settings_response import WorkspaceModelSettingsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceModelSettingsResponse from a JSON string
workspace_model_settings_response_instance = WorkspaceModelSettingsResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceModelSettingsResponse.to_json())

# convert the object into a dict
workspace_model_settings_response_dict = workspace_model_settings_response_instance.to_dict()
# create an instance of WorkspaceModelSettingsResponse from a dict
workspace_model_settings_response_from_dict = WorkspaceModelSettingsResponse.from_dict(workspace_model_settings_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


