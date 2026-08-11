# AgentRuntimeActionErrorResponse

FastAPI envelope for a dedicated Runtime action error.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**detail** | [**AgentRuntimeActionErrorDetail**](AgentRuntimeActionErrorDetail.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_action_error_response import AgentRuntimeActionErrorResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeActionErrorResponse from a JSON string
agent_runtime_action_error_response_instance = AgentRuntimeActionErrorResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeActionErrorResponse.to_json())

# convert the object into a dict
agent_runtime_action_error_response_dict = agent_runtime_action_error_response_instance.to_dict()
# create an instance of AgentRuntimeActionErrorResponse from a dict
agent_runtime_action_error_response_from_dict = AgentRuntimeActionErrorResponse.from_dict(agent_runtime_action_error_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


