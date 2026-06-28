# AgentWorkspaceActionResponse

Agent Workspace state transition action response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Action type |
**method** | **str** | HTTP method |
**path** | **str** | API path to call |

## Example

```python
from azentspublicclient.models.agent_workspace_action_response import AgentWorkspaceActionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceActionResponse from a JSON string
agent_workspace_action_response_instance = AgentWorkspaceActionResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceActionResponse.to_json())

# convert the object into a dict
agent_workspace_action_response_dict = agent_workspace_action_response_instance.to_dict()
# create an instance of AgentWorkspaceActionResponse from a dict
agent_workspace_action_response_from_dict = AgentWorkspaceActionResponse.from_dict(agent_workspace_action_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


