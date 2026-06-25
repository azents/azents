# AgentWorkspaceActionsResponse

Agent Runtime lifecycle action set response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**start** | [**AgentWorkspaceActionResponse**](AgentWorkspaceActionResponse.md) |  | [optional] 
**stop** | [**AgentWorkspaceActionResponse**](AgentWorkspaceActionResponse.md) |  | [optional] 
**restart** | [**AgentWorkspaceActionResponse**](AgentWorkspaceActionResponse.md) |  | [optional] 
**reset** | [**AgentWorkspaceActionResponse**](AgentWorkspaceActionResponse.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.agent_workspace_actions_response import AgentWorkspaceActionsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceActionsResponse from a JSON string
agent_workspace_actions_response_instance = AgentWorkspaceActionsResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceActionsResponse.to_json())

# convert the object into a dict
agent_workspace_actions_response_dict = agent_workspace_actions_response_instance.to_dict()
# create an instance of AgentWorkspaceActionsResponse from a dict
agent_workspace_actions_response_from_dict = AgentWorkspaceActionsResponse.from_dict(agent_workspace_actions_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


