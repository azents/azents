# AgentRuntimeAdditionResponse

Committed or replayed Runtime addition.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**runtime** | [**AgentRuntimeResponse**](AgentRuntimeResponse.md) |  | 
**replayed** | **bool** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_addition_response import AgentRuntimeAdditionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeAdditionResponse from a JSON string
agent_runtime_addition_response_instance = AgentRuntimeAdditionResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeAdditionResponse.to_json())

# convert the object into a dict
agent_runtime_addition_response_dict = agent_runtime_addition_response_instance.to_dict()
# create an instance of AgentRuntimeAdditionResponse from a dict
agent_runtime_addition_response_from_dict = AgentRuntimeAdditionResponse.from_dict(agent_runtime_addition_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


