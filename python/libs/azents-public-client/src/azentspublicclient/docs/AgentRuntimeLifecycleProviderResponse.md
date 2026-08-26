# AgentRuntimeLifecycleProviderResponse

Current Provider lifecycle facts.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**connection** | [**RuntimeProviderConnectionState**](RuntimeProviderConnectionState.md) |  | 
**resource** | [**RuntimeProviderObservedState**](RuntimeProviderObservedState.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_lifecycle_provider_response import AgentRuntimeLifecycleProviderResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeLifecycleProviderResponse from a JSON string
agent_runtime_lifecycle_provider_response_instance = AgentRuntimeLifecycleProviderResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeLifecycleProviderResponse.to_json())

# convert the object into a dict
agent_runtime_lifecycle_provider_response_dict = agent_runtime_lifecycle_provider_response_instance.to_dict()
# create an instance of AgentRuntimeLifecycleProviderResponse from a dict
agent_runtime_lifecycle_provider_response_from_dict = AgentRuntimeLifecycleProviderResponse.from_dict(agent_runtime_lifecycle_provider_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


