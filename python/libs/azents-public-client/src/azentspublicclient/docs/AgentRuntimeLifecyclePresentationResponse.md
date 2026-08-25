# AgentRuntimeLifecyclePresentationResponse

Server-authoritative Runtime lifecycle presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**target** | [**RuntimeDesiredState**](RuntimeDesiredState.md) |  | 
**convergence** | **str** |  | 
**provider** | [**AgentRuntimeLifecycleProviderResponse**](AgentRuntimeLifecycleProviderResponse.md) |  | 
**runner** | [**AgentRuntimeLifecycleRunnerResponse**](AgentRuntimeLifecycleRunnerResponse.md) |  | 
**availability** | **str** |  | 
**reason_code** | **str** |  | 
**desired_generation** | **int** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_lifecycle_presentation_response import AgentRuntimeLifecyclePresentationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeLifecyclePresentationResponse from a JSON string
agent_runtime_lifecycle_presentation_response_instance = AgentRuntimeLifecyclePresentationResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeLifecyclePresentationResponse.to_json())

# convert the object into a dict
agent_runtime_lifecycle_presentation_response_dict = agent_runtime_lifecycle_presentation_response_instance.to_dict()
# create an instance of AgentRuntimeLifecyclePresentationResponse from a dict
agent_runtime_lifecycle_presentation_response_from_dict = AgentRuntimeLifecyclePresentationResponse.from_dict(agent_runtime_lifecycle_presentation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


