# AgentRuntimeActionsResponse

Agent Runtime action availability response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**start** | **bool** |  |
**stop** | **bool** |  |
**restart** | **bool** |  |
**reset** | **bool** |  |
**use_runner** | **bool** |  |

## Example

```python
from azentspublicclient.models.agent_runtime_actions_response import AgentRuntimeActionsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeActionsResponse from a JSON string
agent_runtime_actions_response_instance = AgentRuntimeActionsResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeActionsResponse.to_json())

# convert the object into a dict
agent_runtime_actions_response_dict = agent_runtime_actions_response_instance.to_dict()
# create an instance of AgentRuntimeActionsResponse from a dict
agent_runtime_actions_response_from_dict = AgentRuntimeActionsResponse.from_dict(agent_runtime_actions_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


