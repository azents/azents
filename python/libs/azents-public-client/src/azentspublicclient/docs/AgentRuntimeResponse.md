# AgentRuntimeResponse

Unified capability-aware Agent Runtime response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**capability** | [**AgentRuntimeCapability**](AgentRuntimeCapability.md) |  | 
**capability_version** | **int** |  | 
**runtime_profile_id** | **str** |  | 
**runtime_profile_selection_version** | **int** |  | 
**runtime_profile_status** | **str** |  | 
**runtime_profile_available** | **bool** |  | 
**runtime_profile_availability_reason_code** | **str** |  | 
**removal_impact** | [**AgentRuntimeRemovalImpactResponse**](AgentRuntimeRemovalImpactResponse.md) |  | 
**removal** | [**AgentRuntimeRemovalProgressResponse**](AgentRuntimeRemovalProgressResponse.md) |  | 
**runtime** | [**AgentRuntimeRawStateResponse**](AgentRuntimeRawStateResponse.md) |  | 
**state** | [**AgentRuntimeSummaryResponse**](AgentRuntimeSummaryResponse.md) |  | 
**configuration** | [**AgentRuntimeConfigurationStatusResponse**](AgentRuntimeConfigurationStatusResponse.md) |  | 
**actions** | [**AgentRuntimePublicActionsResponse**](AgentRuntimePublicActionsResponse.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeResponse from a JSON string
agent_runtime_response_instance = AgentRuntimeResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeResponse.to_json())

# convert the object into a dict
agent_runtime_response_dict = agent_runtime_response_instance.to_dict()
# create an instance of AgentRuntimeResponse from a dict
agent_runtime_response_from_dict = AgentRuntimeResponse.from_dict(agent_runtime_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


