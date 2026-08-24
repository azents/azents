# AgentRuntimeSystemMetricCurrentResponse

Current public projection for one Runtime metric.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**state** | [**RuntimeSystemMetricState**](RuntimeSystemMetricState.md) |  | 
**measured_at** | **datetime** |  | 
**used** | **int** |  | 
**total** | **int** |  | 
**percentage** | **float** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_system_metric_current_response import AgentRuntimeSystemMetricCurrentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeSystemMetricCurrentResponse from a JSON string
agent_runtime_system_metric_current_response_instance = AgentRuntimeSystemMetricCurrentResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeSystemMetricCurrentResponse.to_json())

# convert the object into a dict
agent_runtime_system_metric_current_response_dict = agent_runtime_system_metric_current_response_instance.to_dict()
# create an instance of AgentRuntimeSystemMetricCurrentResponse from a dict
agent_runtime_system_metric_current_response_from_dict = AgentRuntimeSystemMetricCurrentResponse.from_dict(agent_runtime_system_metric_current_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


