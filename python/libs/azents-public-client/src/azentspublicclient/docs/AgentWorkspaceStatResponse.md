# AgentWorkspaceStatResponse

Agent Workspace path metadata response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** | Agent Workspace path |
**name** | **str** | Path basename |
**kind** | **str** | Path kind |
**size** | **int** |  | [optional]
**media_type** | **str** |  | [optional]
**modified_at** | **datetime** |  | [optional]
**symlink** | **bool** | Whether the path itself is a symlink |
**real_path** | **str** |  | [optional]
**resolved_kind** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.agent_workspace_stat_response import AgentWorkspaceStatResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceStatResponse from a JSON string
agent_workspace_stat_response_instance = AgentWorkspaceStatResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceStatResponse.to_json())

# convert the object into a dict
agent_workspace_stat_response_dict = agent_workspace_stat_response_instance.to_dict()
# create an instance of AgentWorkspaceStatResponse from a dict
agent_workspace_stat_response_from_dict = AgentWorkspaceStatResponse.from_dict(agent_workspace_stat_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


