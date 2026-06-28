# AgentWorkspaceMutationResponse

Agent Workspace mutation response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** | Affected path |

## Example

```python
from azentspublicclient.models.agent_workspace_mutation_response import AgentWorkspaceMutationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceMutationResponse from a JSON string
agent_workspace_mutation_response_instance = AgentWorkspaceMutationResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceMutationResponse.to_json())

# convert the object into a dict
agent_workspace_mutation_response_dict = agent_workspace_mutation_response_instance.to_dict()
# create an instance of AgentWorkspaceMutationResponse from a dict
agent_workspace_mutation_response_from_dict = AgentWorkspaceMutationResponse.from_dict(agent_workspace_mutation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


