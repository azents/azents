# AgentWorkspaceDirectoryResponse

Agent Workspace directory response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type | 
**path** | **str** | Directory path | 
**entries** | [**List[AgentWorkspaceEntryResponse]**](AgentWorkspaceEntryResponse.md) | Entry list | 

## Example

```python
from azentspublicclient.models.agent_workspace_directory_response import AgentWorkspaceDirectoryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceDirectoryResponse from a JSON string
agent_workspace_directory_response_instance = AgentWorkspaceDirectoryResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceDirectoryResponse.to_json())

# convert the object into a dict
agent_workspace_directory_response_dict = agent_workspace_directory_response_instance.to_dict()
# create an instance of AgentWorkspaceDirectoryResponse from a dict
agent_workspace_directory_response_from_dict = AgentWorkspaceDirectoryResponse.from_dict(agent_workspace_directory_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


