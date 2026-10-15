# AgentWorkspaceEnvironmentSettings

Catalog and explicit selection; defaults contain no selected IDs.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**entries** | [**List[WorkspaceEnvironmentEntry]**](WorkspaceEnvironmentEntry.md) |  | 
**selected_ids** | **List[str]** |  | 
**overridden_names** | **List[str]** |  | 
**can_manage** | **bool** |  | 

## Example

```python
from azentspublicclient.models.agent_workspace_environment_settings import AgentWorkspaceEnvironmentSettings

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceEnvironmentSettings from a JSON string
agent_workspace_environment_settings_instance = AgentWorkspaceEnvironmentSettings.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceEnvironmentSettings.to_json())

# convert the object into a dict
agent_workspace_environment_settings_dict = agent_workspace_environment_settings_instance.to_dict()
# create an instance of AgentWorkspaceEnvironmentSettings from a dict
agent_workspace_environment_settings_from_dict = AgentWorkspaceEnvironmentSettings.from_dict(agent_workspace_environment_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


