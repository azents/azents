# AgentRuntimeRemovalResponse

Committed or replayed Runtime removal.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**runtime** | [**AgentRuntimeResponse**](AgentRuntimeResponse.md) |  | 
**replayed** | **bool** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_removal_response import AgentRuntimeRemovalResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeRemovalResponse from a JSON string
agent_runtime_removal_response_instance = AgentRuntimeRemovalResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeRemovalResponse.to_json())

# convert the object into a dict
agent_runtime_removal_response_dict = agent_runtime_removal_response_instance.to_dict()
# create an instance of AgentRuntimeRemovalResponse from a dict
agent_runtime_removal_response_from_dict = AgentRuntimeRemovalResponse.from_dict(agent_runtime_removal_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


