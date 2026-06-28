# AgentWorkspaceDeleteRequest

Agent Workspace delete request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** | File or directory path to delete |
**recursive** | **bool** | Delete directories recursively | [optional] [default to False]

## Example

```python
from azentspublicclient.models.agent_workspace_delete_request import AgentWorkspaceDeleteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceDeleteRequest from a JSON string
agent_workspace_delete_request_instance = AgentWorkspaceDeleteRequest.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceDeleteRequest.to_json())

# convert the object into a dict
agent_workspace_delete_request_dict = agent_workspace_delete_request_instance.to_dict()
# create an instance of AgentWorkspaceDeleteRequest from a dict
agent_workspace_delete_request_from_dict = AgentWorkspaceDeleteRequest.from_dict(agent_workspace_delete_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


