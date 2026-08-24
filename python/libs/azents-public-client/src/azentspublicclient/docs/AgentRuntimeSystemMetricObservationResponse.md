# AgentRuntimeSystemMetricObservationResponse

One normalized public observation in a retained sample.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**availability** | [**RunnerSystemMetricAvailability**](RunnerSystemMetricAvailability.md) |  | 
**used** | **int** |  | 
**total** | **int** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_system_metric_observation_response import AgentRuntimeSystemMetricObservationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeSystemMetricObservationResponse from a JSON string
agent_runtime_system_metric_observation_response_instance = AgentRuntimeSystemMetricObservationResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeSystemMetricObservationResponse.to_json())

# convert the object into a dict
agent_runtime_system_metric_observation_response_dict = agent_runtime_system_metric_observation_response_instance.to_dict()
# create an instance of AgentRuntimeSystemMetricObservationResponse from a dict
agent_runtime_system_metric_observation_response_from_dict = AgentRuntimeSystemMetricObservationResponse.from_dict(agent_runtime_system_metric_observation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


