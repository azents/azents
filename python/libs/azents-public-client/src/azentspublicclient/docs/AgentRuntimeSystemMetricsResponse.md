# AgentRuntimeSystemMetricsResponse

Dedicated privacy-safe Runtime system-metrics overview.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**summary** | [**RuntimeSystemMetricsSummary**](RuntimeSystemMetricsSummary.md) |  | 
**scope** | [**RunnerSystemMetricsScope**](RunnerSystemMetricsScope.md) |  | 
**cpu** | [**AgentRuntimeSystemMetricCurrentResponse**](AgentRuntimeSystemMetricCurrentResponse.md) |  | 
**memory** | [**AgentRuntimeSystemMetricCurrentResponse**](AgentRuntimeSystemMetricCurrentResponse.md) |  | 
**disk** | [**AgentRuntimeSystemMetricCurrentResponse**](AgentRuntimeSystemMetricCurrentResponse.md) |  | 
**samples** | [**List[AgentRuntimeSystemMetricsSampleResponse]**](AgentRuntimeSystemMetricsSampleResponse.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_system_metrics_response import AgentRuntimeSystemMetricsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeSystemMetricsResponse from a JSON string
agent_runtime_system_metrics_response_instance = AgentRuntimeSystemMetricsResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeSystemMetricsResponse.to_json())

# convert the object into a dict
agent_runtime_system_metrics_response_dict = agent_runtime_system_metrics_response_instance.to_dict()
# create an instance of AgentRuntimeSystemMetricsResponse from a dict
agent_runtime_system_metrics_response_from_dict = AgentRuntimeSystemMetricsResponse.from_dict(agent_runtime_system_metrics_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


