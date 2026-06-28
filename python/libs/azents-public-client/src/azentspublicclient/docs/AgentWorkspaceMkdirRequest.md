# AgentWorkspaceMkdirRequest

Agent Workspace mkdir request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** | Directory path to create |
**parents** | **bool** | Create parent directories | [optional] [default to False]

## Example

```python
from azentspublicclient.models.agent_workspace_mkdir_request import AgentWorkspaceMkdirRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceMkdirRequest from a JSON string
agent_workspace_mkdir_request_instance = AgentWorkspaceMkdirRequest.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceMkdirRequest.to_json())

# convert the object into a dict
agent_workspace_mkdir_request_dict = agent_workspace_mkdir_request_instance.to_dict()
# create an instance of AgentWorkspaceMkdirRequest from a dict
agent_workspace_mkdir_request_from_dict = AgentWorkspaceMkdirRequest.from_dict(agent_workspace_mkdir_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


