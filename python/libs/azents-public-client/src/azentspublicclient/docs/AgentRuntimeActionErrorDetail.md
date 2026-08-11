# AgentRuntimeActionErrorDetail

Stable dedicated Runtime action error.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** |  | 
**message** | **str** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_action_error_detail import AgentRuntimeActionErrorDetail

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeActionErrorDetail from a JSON string
agent_runtime_action_error_detail_instance = AgentRuntimeActionErrorDetail.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeActionErrorDetail.to_json())

# convert the object into a dict
agent_runtime_action_error_detail_dict = agent_runtime_action_error_detail_instance.to_dict()
# create an instance of AgentRuntimeActionErrorDetail from a dict
agent_runtime_action_error_detail_from_dict = AgentRuntimeActionErrorDetail.from_dict(agent_runtime_action_error_detail_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


