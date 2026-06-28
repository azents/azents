# AgentRuntimeLifecycleResponse

Agent Runtime lifecycle command response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**runtime** | [**AgentRuntimeRawStateResponse**](AgentRuntimeRawStateResponse.md) |  |
**state** | [**AgentRuntimeSummaryResponse**](AgentRuntimeSummaryResponse.md) |  |
**command_type** | [**RuntimeLifecycleCommandType**](RuntimeLifecycleCommandType.md) |  |
**desired_generation** | **int** |  |

## Example

```python
from azentspublicclient.models.agent_runtime_lifecycle_response import AgentRuntimeLifecycleResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeLifecycleResponse from a JSON string
agent_runtime_lifecycle_response_instance = AgentRuntimeLifecycleResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeLifecycleResponse.to_json())

# convert the object into a dict
agent_runtime_lifecycle_response_dict = agent_runtime_lifecycle_response_instance.to_dict()
# create an instance of AgentRuntimeLifecycleResponse from a dict
agent_runtime_lifecycle_response_from_dict = AgentRuntimeLifecycleResponse.from_dict(agent_runtime_lifecycle_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


