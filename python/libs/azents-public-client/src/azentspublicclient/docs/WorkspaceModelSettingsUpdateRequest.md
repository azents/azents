# WorkspaceModelSettingsUpdateRequest

Workspace model settings update request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**default_model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) |  | [optional]
**default_lightweight_model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) |  | [optional]

## Example

```python
from azentspublicclient.models.workspace_model_settings_update_request import WorkspaceModelSettingsUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceModelSettingsUpdateRequest from a JSON string
workspace_model_settings_update_request_instance = WorkspaceModelSettingsUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceModelSettingsUpdateRequest.to_json())

# convert the object into a dict
workspace_model_settings_update_request_dict = workspace_model_settings_update_request_instance.to_dict()
# create an instance of WorkspaceModelSettingsUpdateRequest from a dict
workspace_model_settings_update_request_from_dict = WorkspaceModelSettingsUpdateRequest.from_dict(workspace_model_settings_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
