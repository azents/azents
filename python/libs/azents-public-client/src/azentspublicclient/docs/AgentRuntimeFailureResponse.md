# AgentRuntimeFailureResponse

Agent Runtime failure response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**generation** | **int** |  | 
**code** | **str** |  | 
**message** | **str** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_failure_response import AgentRuntimeFailureResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeFailureResponse from a JSON string
agent_runtime_failure_response_instance = AgentRuntimeFailureResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeFailureResponse.to_json())

# convert the object into a dict
agent_runtime_failure_response_dict = agent_runtime_failure_response_instance.to_dict()
# create an instance of AgentRuntimeFailureResponse from a dict
agent_runtime_failure_response_from_dict = AgentRuntimeFailureResponse.from_dict(agent_runtime_failure_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


