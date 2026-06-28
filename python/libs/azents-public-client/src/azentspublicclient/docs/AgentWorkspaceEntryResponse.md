# AgentWorkspaceEntryResponse

Agent Workspace directory entry response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | File or directory name |
**path** | **str** | Agent Workspace absolute path |
**kind** | **str** | Entry kind |
**size** | **int** |  | [optional]
**media_type** | **str** |  | [optional]
**modified_at** | **datetime** |  | [optional]

## Example

```python
from azentspublicclient.models.agent_workspace_entry_response import AgentWorkspaceEntryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceEntryResponse from a JSON string
agent_workspace_entry_response_instance = AgentWorkspaceEntryResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceEntryResponse.to_json())

# convert the object into a dict
agent_workspace_entry_response_dict = agent_workspace_entry_response_instance.to_dict()
# create an instance of AgentWorkspaceEntryResponse from a dict
agent_workspace_entry_response_from_dict = AgentWorkspaceEntryResponse.from_dict(agent_workspace_entry_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


