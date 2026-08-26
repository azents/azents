# AgentRuntimeLifecycleRunnerResponse

Current Runner lifecycle fact.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**state** | [**RuntimeRunnerState**](RuntimeRunnerState.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_lifecycle_runner_response import AgentRuntimeLifecycleRunnerResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeLifecycleRunnerResponse from a JSON string
agent_runtime_lifecycle_runner_response_instance = AgentRuntimeLifecycleRunnerResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeLifecycleRunnerResponse.to_json())

# convert the object into a dict
agent_runtime_lifecycle_runner_response_dict = agent_runtime_lifecycle_runner_response_instance.to_dict()
# create an instance of AgentRuntimeLifecycleRunnerResponse from a dict
agent_runtime_lifecycle_runner_response_from_dict = AgentRuntimeLifecycleRunnerResponse.from_dict(agent_runtime_lifecycle_runner_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


