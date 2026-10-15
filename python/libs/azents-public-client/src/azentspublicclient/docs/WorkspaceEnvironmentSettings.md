# WorkspaceEnvironmentSettings

Redacted shared configuration and editing authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**entries** | [**List[WorkspaceEnvironmentEntry]**](WorkspaceEnvironmentEntry.md) |  | 
**can_manage** | **bool** |  | 

## Example

```python
from azentspublicclient.models.workspace_environment_settings import WorkspaceEnvironmentSettings

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceEnvironmentSettings from a JSON string
workspace_environment_settings_instance = WorkspaceEnvironmentSettings.from_json(json)
# print the JSON string representation of the object
print(WorkspaceEnvironmentSettings.to_json())

# convert the object into a dict
workspace_environment_settings_dict = workspace_environment_settings_instance.to_dict()
# create an instance of WorkspaceEnvironmentSettings from a dict
workspace_environment_settings_from_dict = WorkspaceEnvironmentSettings.from_dict(workspace_environment_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


