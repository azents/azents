# AgentRuntimeSystemMetricsSampleResponse

One retained public Runtime metrics sample.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**measured_at** | **datetime** |  | 
**scope** | [**RunnerSystemMetricsScope**](RunnerSystemMetricsScope.md) |  | 
**cpu** | [**AgentRuntimeSystemMetricObservationResponse**](AgentRuntimeSystemMetricObservationResponse.md) |  | 
**memory** | [**AgentRuntimeSystemMetricObservationResponse**](AgentRuntimeSystemMetricObservationResponse.md) |  | 
**disk** | [**AgentRuntimeSystemMetricObservationResponse**](AgentRuntimeSystemMetricObservationResponse.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_system_metrics_sample_response import AgentRuntimeSystemMetricsSampleResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeSystemMetricsSampleResponse from a JSON string
agent_runtime_system_metrics_sample_response_instance = AgentRuntimeSystemMetricsSampleResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeSystemMetricsSampleResponse.to_json())

# convert the object into a dict
agent_runtime_system_metrics_sample_response_dict = agent_runtime_system_metrics_sample_response_instance.to_dict()
# create an instance of AgentRuntimeSystemMetricsSampleResponse from a dict
agent_runtime_system_metrics_sample_response_from_dict = AgentRuntimeSystemMetricsSampleResponse.from_dict(agent_runtime_system_metrics_sample_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


